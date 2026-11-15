"""Run one managed local Web server with private lifecycle metadata."""

import argparse
from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import socket
import stat
from uuid import uuid4

from . import __version__
from .web_identity import API_VERSION, RUNTIME_PROTOCOL, SERVICE_NAME, inspect_ui, workspace_identity
from .web_runtime import _directory, _file_lock, _remove_descriptor, _runtime_directory, _write_descriptor


def _logging(directory: Path) -> None:
    """Inputs: an owner-only runtime directory.
    Outputs: bounded private diagnostics for the child process.

    Logic: rotate logs, reject links, and disable verbose request logging.
    Dependencies: standard logging and RotatingFileHandler.
    """
    path = directory / "server.log"
    if path.is_symlink() or (directory / "server.log.1").is_symlink():
        raise OSError("Runtime logs must not be symbolic links.")
    for candidate in (path, directory / "server.log.1"):
        if candidate.exists() and not stat.S_ISREG(candidate.stat().st_mode):
            raise OSError("Runtime logs must be regular files.")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    os.fchmod(descriptor, 0o600)
    os.close(descriptor)
    handler = RotatingFileHandler(path, maxBytes=262_144, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(handlers=[handler], level=logging.WARNING, force=True)
    logging.getLogger("uvicorn.access").disabled = True


def _listener(preferred_port: int) -> socket.socket:
    """Inputs: a preferred loopback port, with zero requesting OS allocation.
    Outputs: a bound nonblocking socket retained for Uvicorn.

    Logic: bind once; use an OS-selected port if the preferred port is occupied.
    Dependencies: socket and the local network stack.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", preferred_port))
        except OSError:
            if preferred_port == 0:
                raise
            listener.bind(("127.0.0.1", 0))
        listener.setblocking(False)
        return listener
    except BaseException:
        listener.close()
        raise


def _serve(data_dir: Path, static_dir: Path, preferred_port: int, runtime: Path) -> int:
    """Inputs: validated authority, UI location, preferred port, and runtime folder.
    Outputs: the managed server's exit code.

    Logic: register only after app startup and remove only this instance on exit.
    Dependencies: optional Uvicorn and FastAPI; caller holds the lifetime lock.
    """
    import uvicorn
    from .http_api import create_app

    identity = workspace_identity(data_dir)
    assets = inspect_ui(static_dir)
    if not assets["ui_ready"]:
        return 1
    instance_id = str(uuid4())
    control_token = secrets.token_urlsafe(32)
    listener = _listener(preferred_port)
    port = listener.getsockname()[1]
    description = {"_comment": "Describe this private managed Web instance; never publish its control token.",
                   "service": SERVICE_NAME, "runtime_protocol": RUNTIME_PROTOCOL,
                   "api_version": API_VERSION, "app_version": __version__, **identity,
                   "instance_id": instance_id, "port": port, "pid": os.getpid(),
                   "started_at": datetime.now(timezone.utc).isoformat(),
                   "ui_build_id": assets["ui_build_id"], "control_token": control_token}

    class RegisteredServer(uvicorn.Server):
        """Publish the actual bound address only after application startup."""

        async def startup(self, sockets: list[socket.socket] | None = None) -> None:
            """Inputs: retained listening sockets. Outputs: a ready registration.

            Logic: let Uvicorn finish startup before publishing private instance data.
            Dependencies: Uvicorn startup and atomic runtime description writes.
            """
            await super().startup(sockets=sockets)
            if self.started:
                _write_descriptor(runtime, description)

    server = None

    def request_shutdown() -> None:
        """Inputs: an authenticated shutdown callback. Outputs: graceful server exit.

        Logic: ask the current server loop to stop after the control response.
        Dependencies: this exact Uvicorn instance, not a process ID lookup.
        """
        if server is not None:
            server.should_exit = True

    app = create_app(data_dir, static_dir, runtime_context={"instance_id": instance_id, **identity},
                     control_token=control_token, request_shutdown=request_shutdown)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, proxy_headers=False,
                            access_log=False, log_config=None, log_level="warning",
                            timeout_graceful_shutdown=10)
    server = RegisteredServer(config)
    try:
        server.run(sockets=[listener])
        return 0 if server.started else 1
    finally:
        listener.close()
        _remove_descriptor(runtime, instance_id)


def main(argv: list[str] | None = None) -> int:
    """Inputs: private data, built assets, and preferred port arguments.
    Outputs: a child process exit code with private bounded diagnostics.

    Logic: validate existing resources, hold the server lock, and serve one instance.
    Dependencies: runtime helpers, optional Web packages, and no shell commands.
    """
    parser = argparse.ArgumentParser(description="Run a managed local feedback server.")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--static-dir", required=True)
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args(argv)
    try:
        os.umask(0o077)
        directory = _directory(Path(arguments.data_dir))
        workspace_identity(directory)
        assets = Path(arguments.static_dir).expanduser()
        if not assets.is_absolute() or not 0 <= arguments.port <= 65535:
            return 1
        runtime = _runtime_directory(directory, create=True)
        _logging(runtime)
        with _file_lock(runtime / "server.lock") as acquired:
            if not acquired:
                return 2
            return _serve(directory, assets, arguments.port, runtime)
    except Exception as error:
        logging.error("Local Web startup failed (%s).", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
