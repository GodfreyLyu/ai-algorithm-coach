"""Manage optional local Web instances without importing Web frameworks."""

from contextlib import contextmanager
import http.client
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import tomllib
from uuid import UUID, uuid4

from .. import __version__
from ..errors import CoachError
from .identity import API_VERSION, RUNTIME_PROTOCOL, SERVICE_NAME, inspect_ui, store_id, workspace_identity

try:
    import fcntl
except ImportError:
    fcntl = None


MAX_RUNTIME_BYTES = 65_536
RUNTIME_DIRECTORY = ".web-runtime"
RUNTIME_FILE = "runtime.json"
_CHILDREN: dict[int, subprocess.Popen] = {}


def _result(status: str, reason: str | None = None, **fields: object) -> dict:
    """Inputs: a public state, stable reason, and safe runtime fields.
    Outputs: a JSON-compatible result without paths or control credentials.

    Logic: expose a fixed public field set and omit absent values.
    Dependencies: the local runtime result contract.
    """
    allowed = {"action", "url", "instance_id", "store_id", "workspace_id", "app_version", "ui_build_id"}
    result = {"status": status}
    if reason is not None:
        result["reason"] = reason
    result.update({key: value for key, value in fields.items() if key in allowed and value is not None})
    return result


def _directory(data_dir: Path) -> Path:
    """Inputs: a configured private data directory.
    Outputs: its canonical existing absolute location.

    Logic: reject relative paths and leave setup to explicit initialization.
    Dependencies: pathlib and CoachError.
    """
    path = Path(data_dir).expanduser()
    if not path.is_absolute():
        raise CoachError("validation_error", "Use an absolute data directory.")
    return path.resolve()


def _timeout(value: float) -> float:
    """Inputs: a request or startup time limit.
    Outputs: a finite positive floating-point duration.

    Logic: reject unbounded and boolean time limits before process work.
    Dependencies: math and CoachError.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise CoachError("validation_error", "Use a finite positive timeout.")
    return float(value)


def _regular_json(path: Path) -> dict | None:
    """Inputs: a private runtime description path.
    Outputs: one bounded object, or no valid description.

    Logic: reject links, oversized files, invalid JSON, and non-object roots.
    Dependencies: os file descriptors, stat, and json.
    """
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_RUNTIME_BYTES:
            return None
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            result = json.load(stream)
        return result if isinstance(result, dict) else None
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _runtime_directory(data_dir: Path, create: bool = False) -> Path:
    """Inputs: the authority directory and whether creation is authorized.
    Outputs: a private runtime directory path.

    Logic: reject symbolic links and restrict created runtime files to the owner.
    Dependencies: pathlib, os permissions, and an existing authority directory.
    """
    directory = data_dir / RUNTIME_DIRECTORY
    if directory.is_symlink():
        raise OSError("The runtime directory must not be a symbolic link.")
    if create:
        directory.mkdir(mode=0o700, exist_ok=True)
        if not directory.is_dir():
            raise OSError("The runtime directory is invalid.")
        directory.chmod(0o700)
    return directory


@contextmanager
def _file_lock(path: Path, timeout: float = 0, create: bool = True):
    """Inputs: a lock path, bounded wait, and file-creation policy.
    Outputs: whether this process acquired the advisory exclusive lock.

    Logic: use an OS lock that is released after a crash; never trust a PID file.
    Dependencies: POSIX flock, private regular files, and a monotonic clock.
    """
    if fcntl is None:
        yield False
        return
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    if create:
        flags |= os.O_CREAT
    descriptor = os.open(path, flags, 0o600)
    acquired = False
    deadline = time.monotonic() + timeout
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("A runtime lock must be a regular file.")
        if create:
            os.fchmod(descriptor, 0o600)
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        yield acquired
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _server_locked(directory: Path) -> bool:
    """Inputs: the private runtime directory.
    Outputs: whether a process holds the managed server's lifetime lock.

    Logic: inspect the existing lock without creating state during status reads.
    Dependencies: _file_lock and POSIX lock release semantics.
    """
    try:
        with _file_lock(directory / "server.lock", create=False) as acquired:
            return not acquired
    except FileNotFoundError:
        return False


def _write_descriptor(directory: Path, value: dict) -> None:
    """Inputs: a private runtime directory and one instance description.
    Outputs: an atomically replaced owner-only runtime file.

    Logic: flush a fresh temporary file before replacing the description.
    Dependencies: os descriptors, fsync, json, and UUID temporary names.
    """
    temporary = directory / (".runtime-" + uuid4().hex + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / RUNTIME_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def _remove_descriptor(directory: Path, instance_id: str | None = None) -> None:
    """Inputs: a runtime directory and optional expected instance identity.
    Outputs: removal of only the eligible runtime description.

    Logic: keep another instance's description and reject symbolic links.
    Dependencies: _regular_json and the lifetime lock held by the caller.
    """
    path = directory / RUNTIME_FILE
    if path.is_symlink():
        raise OSError("The runtime description must not be a symbolic link.")
    current = _regular_json(path)
    if instance_id is None or current is not None and current.get("instance_id") == instance_id:
        path.unlink(missing_ok=True)


def _request(port: int, endpoint: str, timeout: float, *, payload: dict | None = None, token: str | None = None) -> dict | None:
    """Inputs: a validated local port, endpoint, timeout, and optional control body.
    Outputs: a successful bounded JSON data object, or no usable response.

    Logic: contact loopback directly without proxies or redirect following.
    Dependencies: http.client and the local API envelope.
    """
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        headers = {"Origin": f"http://127.0.0.1:{port}"}
        body = None
        if payload is not None:
            body = json.dumps(payload, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["X-Coach-Control-Token"] = token
        connection.request("POST" if payload is not None else "GET", endpoint, body=body, headers=headers)
        response = connection.getresponse()
        content = response.read(MAX_RUNTIME_BYTES + 1)
        if response.status != 200 or len(content) > MAX_RUNTIME_BYTES:
            return None
        result = json.loads(content)
        if not isinstance(result, dict) or result.get("ok") is not True or not isinstance(result.get("data"), dict):
            return None
        return result["data"]
    except (OSError, ValueError, http.client.HTTPException, RecursionError):
        return None
    finally:
        connection.close()


def _description_matches(description: dict, identity: dict) -> bool:
    """Inputs: saved runtime metadata and current authority identity.
    Outputs: whether the metadata is usable for this exact store.

    Logic: require local port, private control identity, and current store binding.
    Dependencies: the versioned managed runtime description contract.
    """
    port = description.get("port")
    return (
        type(port) is int and 1 <= port <= 65535
        and description.get("service") == SERVICE_NAME
        and description.get("runtime_protocol") == RUNTIME_PROTOCOL
        and description.get("workspace_id") == identity["workspace_id"]
        and description.get("store_id") == identity["store_id"]
        and isinstance(description.get("instance_id"), str) and 1 <= len(description["instance_id"]) <= 200
        and isinstance(description.get("control_token"), str) and 20 <= len(description["control_token"]) <= 200
    )


def _control_identity(data_dir: Path, directory: Path) -> dict:
    """Inputs: the authority and its private runtime directory.
    Outputs: a verified current or location-bound startup identity for shutdown.

    Logic: permit safe control after database failure without trusting a copied description.
    Dependencies: the core identity reader, canonical store hashes, and private metadata.
    """
    try:
        return workspace_identity(data_dir)
    except (CoachError, OSError, sqlite3.Error):
        description = _regular_json(directory / RUNTIME_FILE)
        workspace = description.get("workspace_id") if description is not None else None
        try:
            valid_workspace = isinstance(workspace, str) and str(UUID(workspace)) == workspace
        except (ValueError, AttributeError):
            valid_workspace = False
        if not valid_workspace:
            raise CoachError("runtime_identity_mismatch", "Managed store identity is unavailable.") from None
        expected = store_id(data_dir / "coach.sqlite3", workspace)
        if description.get("store_id") != expected:
            raise CoachError("runtime_identity_mismatch", "Managed store identity does not match this location.") from None
        return {"workspace_id": workspace, "store_id": expected}


def _probe(description: dict, identity: dict, timeout: float, build_id: str | None = None,
           check_version: bool = True, require_ready: bool = True) -> dict:
    """Inputs: runtime metadata, store identity, and expected protocol or build.
    Outputs: a sanitized ready result or a stable refusal reason.

    Logic: match a live API response rather than treating an open port as success.
    Dependencies: _request and the managed service identity contract.
    """
    if not _description_matches(description, identity):
        return _result("unavailable", "runtime_identity_mismatch", **identity)
    actual = _request(description["port"], "/v1/runtime", timeout)
    if actual is None:
        return _result("unavailable", "runtime_unresponsive", **identity)
    for name, expected in (("service", SERVICE_NAME), ("runtime_protocol", RUNTIME_PROTOCOL),
                           ("workspace_id", identity["workspace_id"]), ("store_id", identity["store_id"]),
                           ("instance_id", description["instance_id"]), ("managed", True)):
        if actual.get(name) != expected:
            return _result("unavailable", "runtime_identity_mismatch", **identity)
    if actual.get("api_version") != API_VERSION or check_version and actual.get("app_version") != __version__:
        return _result("unavailable", "runtime_version_mismatch", **identity)
    if require_ready and (actual.get("database_ready") is not True or actual.get("ui_ready") is not True):
        return _result("unavailable", "runtime_not_ready", **identity)
    if build_id is not None and actual.get("ui_build_id") != build_id:
        return _result("unavailable", "ui_version_mismatch", **identity)
    return _result("ready", action="reused", url=f"http://127.0.0.1:{description['port']}/",
                   instance_id=description["instance_id"], app_version=actual.get("app_version"),
                   ui_build_id=actual.get("ui_build_id"), **identity)


def _settings(data_dir: Path, python: str | None, static_dir: Path | None, preferred_port: int | None) -> dict:
    """Inputs: the private workspace and optional explicit startup overrides.
    Outputs: validated local settings with discovered installation resources.

    Logic: read optional private TOML; never install dependencies or build assets.
    Dependencies: tomllib, environment settings, and this distribution's layout.
    """
    settings = {}
    config = data_dir / "web.toml"
    if config.exists():
        if config.is_symlink() or config.stat().st_size > MAX_RUNTIME_BYTES:
            raise CoachError("web_config_invalid", "The local Web configuration is invalid.")
        try:
            content = tomllib.loads(config.read_text(encoding="utf-8"))
            settings = content.get("web", {})
        except (OSError, ValueError, UnicodeError) as exc:
            raise CoachError("web_config_invalid", "The local Web configuration is invalid.") from exc
        if not isinstance(settings, dict) or set(settings) - {"enabled", "python", "port", "static_dir"}:
            raise CoachError("web_config_invalid", "The local Web configuration has unsupported fields.")
    enabled = settings.get("enabled", True)
    port = preferred_port if preferred_port is not None else settings.get("port", 8765)
    if type(enabled) is not bool or type(port) is not int or not 0 <= port <= 65535:
        raise CoachError("web_config_invalid", "Use a boolean enabled flag and a valid local port.")
    root = Path(__file__).resolve().parents[3]
    chosen_python = python or os.environ.get("ALGORITHM_COACH_WEB_PYTHON") or settings.get("python")
    if chosen_python is None:
        local_python = root / ".venv-web" / "bin" / "python"
        chosen_python = str(local_python) if local_python.is_file() else sys.executable
    if not isinstance(chosen_python, str) or not chosen_python:
        raise CoachError("web_config_invalid", "Configure one Python executable.")
    expanded = Path(chosen_python).expanduser()
    if not expanded.is_absolute():
        located = shutil.which(chosen_python) if expanded.name == chosen_python else None
        if located is None:
            raise CoachError("web_python_unavailable", "The Web Python executable is unavailable.")
        expanded = Path(located)
    assets = static_dir if static_dir is not None else settings.get("static_dir")
    if assets is not None:
        if not isinstance(assets, (str, Path)):
            raise CoachError("web_config_invalid", "Configure one absolute UI directory.")
        assets = Path(assets).expanduser()
        if not assets.is_absolute():
            raise CoachError("web_config_invalid", "Use an absolute UI directory.")
    else:
        for candidate in (root / "assets" / "web", root / "web" / "dist"):
            if candidate.is_dir():
                assets = candidate
                break
    return {"enabled": enabled, "python": str(expanded), "port": port, "static_dir": assets}


def _python_ready(executable: str, timeout: float) -> str | None:
    """Inputs: a selected Python executable and bounded probe time.
    Outputs: no error, or a stable dependency or interpreter reason.

    Logic: test optional imports in the chosen environment without changing it.
    Dependencies: subprocess and the installed Web packages.
    """
    try:
        result = subprocess.run([executable, "-c", "import fastapi, pydantic, uvicorn"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        return None if result.returncode == 0 else "web_dependencies_missing"
    except (OSError, subprocess.TimeoutExpired):
        return "web_python_unavailable"


def _launch(data_dir: Path, settings: dict) -> subprocess.Popen:
    """Inputs: the exact authority directory and validated Web settings.
    Outputs: one detached child process handle.

    Logic: pass argument arrays and this distribution's import root without a shell.
    Dependencies: subprocess, the optional interpreter, and web.server.
    """
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    arguments = [settings["python"], "-m", "algorithm_coach.web.server", "--data-dir", str(data_dir),
                 "--static-dir", str(settings["static_dir"]), "--port", str(settings["port"])]
    return subprocess.Popen(arguments, cwd=data_dir, env=environment, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True, close_fds=True)


def _reap_children() -> None:
    """Inputs: remembered child handles from this Python process.
    Outputs: reaped exited children without disturbing running services.

    Logic: retain detached handles until exit instead of abandoning live subprocesses.
    Dependencies: Popen.poll and this module's local child registry.
    """
    for pid, child in list(_CHILDREN.items()):
        if child.poll() is not None:
            _CHILDREN.pop(pid, None)


def ensure_web(data_dir: Path, *, python: str | None = None, static_dir: Path | None = None,
               preferred_port: int | None = None, timeout: float = 10) -> dict:
    """Inputs: an existing authority and optional startup overrides.
    Outputs: a ready, disabled, or unavailable result with no private credentials.

    Logic: serialize startup, verify live identity, and start at most one managed server.
    Dependencies: standard-library process tools and optional packages only in the child.
    """
    child = None
    try:
        _reap_children()
        duration = _timeout(timeout)
        directory = _directory(data_dir)
        identity = workspace_identity(directory)
        settings = _settings(directory, python, static_dir, preferred_port)
        if not settings["enabled"]:
            return _result("disabled", "web_disabled", **identity)
        if fcntl is None:
            return _result("unavailable", "unsupported_platform", **identity)
        assets = inspect_ui(settings["static_dir"])
        if not assets["ui_ready"]:
            return _result("unavailable", assets.get("reason") or "ui_assets_missing", **identity)
        runtime = _runtime_directory(directory, create=True)
        deadline = time.monotonic() + duration
        with _file_lock(runtime / "start.lock", duration) as acquired:
            if not acquired:
                return _result("unavailable", "startup_busy", **identity)
            description = _regular_json(runtime / RUNTIME_FILE)
            held = _server_locked(runtime)
            if description is not None:
                current = _probe(description, identity, min(1, max(0.05, deadline - time.monotonic())), assets["ui_build_id"])
                if current["status"] == "ready":
                    return current if held else _result("unavailable", "runtime_lock_missing", **identity)
                if held:
                    return current
            elif held:
                return _result("unavailable", "startup_in_progress", **identity)
            _remove_descriptor(runtime)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _result("unavailable", "startup_timeout", **identity)
            error = _python_ready(settings["python"], min(5, remaining))
            if error:
                return _result("unavailable", error, **identity)
            if time.monotonic() >= deadline:
                return _result("unavailable", "startup_timeout", **identity)
            child = _launch(directory, settings)
            _CHILDREN[child.pid] = child
            while time.monotonic() < deadline:
                description = _regular_json(runtime / RUNTIME_FILE)
                if description is not None:
                    current = _probe(description, identity, min(0.5, max(0.05, deadline - time.monotonic())), assets["ui_build_id"])
                    if current["status"] == "ready" and _server_locked(runtime):
                        current["action"] = "started"
                        return current
                if child.poll() is not None:
                    return _result("unavailable", "startup_failed", **identity)
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            return _result("unavailable", "startup_timeout", **identity)
    except CoachError as exc:
        return _result("unavailable", exc.code)
    except (OSError, ValueError, TypeError):
        return _result("unavailable", "runtime_unavailable")
    finally:
        if child is not None:
            child.poll()
        _reap_children()


def web_status(data_dir: Path, timeout: float = 2) -> dict:
    """Inputs: an existing authority and a bounded local status timeout.
    Outputs: current managed service status without modifying runtime files.

    Logic: verify the stored instance against its live API and lifetime lock.
    Dependencies: standard-library HTTP, existing runtime metadata, and store identity.
    """
    try:
        _reap_children()
        duration = _timeout(timeout)
        directory = _directory(data_dir)
        identity = workspace_identity(directory)
        if fcntl is None:
            return _result("unavailable", "unsupported_platform", **identity)
        runtime = _runtime_directory(directory)
        description = _regular_json(runtime / RUNTIME_FILE)
        held = _server_locked(runtime)
        if description is None:
            return _result("unavailable" if held else "stopped", "startup_in_progress" if held else "not_running", **identity)
        current = _probe(description, identity, duration)
        if current["status"] == "ready":
            return current if held else _result("unavailable", "runtime_lock_missing", **identity)
        return current if held else _result("stopped", "stale_runtime", **identity)
    except CoachError as exc:
        return _result("unavailable", exc.code)
    except (OSError, ValueError, TypeError):
        return _result("unavailable", "runtime_unavailable")


def stop_web(data_dir: Path, timeout: float = 10) -> dict:
    """Inputs: an existing authority and a bounded shutdown time limit.
    Outputs: a stopped result or a clear refusal without signaling arbitrary PIDs.

    Logic: serialize against startup and verify the exact instance before graceful exit.
    Dependencies: the private control token and loopback shutdown endpoint.
    """
    try:
        duration = _timeout(timeout)
        deadline = time.monotonic() + duration
        directory = _directory(data_dir)
        runtime = _runtime_directory(directory)
        identity = _control_identity(directory, runtime)
        if fcntl is None:
            return _result("unavailable", "unsupported_platform", **identity)
        if not runtime.exists():
            return _result("stopped", "not_running", **identity)
        with _file_lock(runtime / "start.lock", max(0, deadline - time.monotonic())) as acquired:
            if not acquired:
                return _result("unavailable", "startup_busy", **identity)
            description = _regular_json(runtime / RUNTIME_FILE)
            held = _server_locked(runtime)
            if not held:
                return _result("stopped", "not_running", **identity)
            if description is None:
                return _result("unavailable", "startup_in_progress", **identity)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _result("unavailable", "shutdown_timeout", **identity)
            current = _probe(description, identity, min(remaining, 2), check_version=False, require_ready=False)
            if current["status"] != "ready":
                return current
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _result("unavailable", "shutdown_timeout", **identity)
            acknowledged = _request(description["port"], "/internal/runtime/stop", min(remaining, 2),
                                    payload={"instance_id": description["instance_id"]}, token=description["control_token"])
            if acknowledged is None or acknowledged.get("instance_id") != description["instance_id"] or acknowledged.get("stopping") is not True:
                return _result("unavailable", "shutdown_not_confirmed", **identity)
            while time.monotonic() < deadline:
                if not _server_locked(runtime):
                    _reap_children()
                    return _result("stopped", action="stopped", instance_id=description["instance_id"], **identity)
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            return _result("unavailable", "shutdown_timeout", **identity)
    except CoachError as exc:
        return _result("unavailable", exc.code)
    except (OSError, ValueError, TypeError):
        return _result("unavailable", "runtime_unavailable")
