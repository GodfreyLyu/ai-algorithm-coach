"""Verify managed local Web startup, identity, concurrency, and crash recovery."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.service import Coach
from algorithm_coach import web_runtime
from algorithm_coach.web_identity import API_VERSION, RUNTIME_PROTOCOL, SERVICE_NAME, workspace_identity


WEB_AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("fastapi", "uvicorn", "pydantic"))
POSIX_AVAILABLE = web_runtime.fcntl is not None


def make_assets(directory: Path) -> Path:
    """Inputs: a temporary location for synthetic static resources.
    Outputs: a valid self-contained UI resource directory.

    Logic: create a small page and the same versioned inventory used by real bundles.
    Dependencies: hashlib, json, and temporary filesystem storage.
    """
    directory.mkdir(parents=True)
    content = b"<!-- File purpose: Provide a synthetic runtime readiness page. -->\n<h1>Practice</h1>"
    (directory / "index.html").write_bytes(content)
    files = {"index.html": hashlib.sha256(content).hexdigest()}
    canonical = json.dumps(files, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    record = {"format_version": 1, "api_version": API_VERSION, "files": files,
              "build_id": hashlib.sha256(canonical.encode()).hexdigest()}
    (directory / "coach-ui-manifest.json").write_text(json.dumps(record), encoding="utf-8")
    return directory


@unittest.skipUnless(POSIX_AVAILABLE, "Managed Web processes currently require POSIX locks.")
class RuntimeUnitTests(unittest.TestCase):
    """Test dependency-free runtime decisions without starting a real Web server."""

    def setUp(self) -> None:
        """Inputs: none. Outputs: an isolated authority and synthetic assets.

        Logic: use a fresh initialized database outside the checkout.
        Dependencies: tempfile, Coach, and make_assets.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.data = self.base / "private"
        self.coach = Coach(self.data / "coach.sqlite3")
        self.coach.initialize({"timezone": "UTC"})
        self.assets = make_assets(self.base / "assets")

    def tearDown(self) -> None:
        """Inputs: the isolated fixture. Outputs: closed data and removed temporary files.

        Logic: close the core connection before deleting only this test's files.
        Dependencies: Coach.close and TemporaryDirectory.cleanup.
        """
        self.coach.close()
        self.temp.cleanup()

    def test_status_and_missing_storage_never_create_runtime_or_database(self) -> None:
        """Inputs: existing and missing authorities. Outputs: read-only status results.

        Logic: check file inventories before and after status and failed startup.
        Dependencies: web_status, ensure_web, and a temporary filesystem.
        """
        before = sorted(path.name for path in self.data.iterdir())
        self.assertEqual(web_runtime.web_status(self.data)["status"], "stopped")
        self.assertEqual(before, sorted(path.name for path in self.data.iterdir()))
        missing = self.base / "missing"
        self.assertEqual(web_runtime.web_status(missing)["status"], "unavailable")
        self.assertEqual(web_runtime.ensure_web(missing, static_dir=self.assets)["status"], "unavailable")
        self.assertFalse(missing.exists())

    def test_disabled_or_missing_assets_do_not_launch_or_install(self) -> None:
        """Inputs: disabled and incomplete Web setups. Outputs: explicit safe fallbacks.

        Logic: refuse startup before creating runtime state or invoking a process.
        Dependencies: private TOML settings, asset checks, and a launch spy.
        """
        (self.data / "web.toml").write_text("# File purpose: Disable this synthetic Web setup.\n[web]\nenabled = false\n", encoding="utf-8")
        with patch.object(web_runtime, "_launch") as launched:
            disabled = web_runtime.ensure_web(self.data, static_dir=self.assets)
            self.assertEqual(disabled["status"], "disabled")
            (self.data / "web.toml").unlink()
            absent = web_runtime.ensure_web(self.data, static_dir=self.base / "absent")
            self.assertEqual(absent["reason"], "assets_missing")
            launched.assert_not_called()
        self.assertFalse((self.data / ".web-runtime").exists())

    def test_missing_dependencies_and_invalid_settings_have_stable_reasons(self) -> None:
        """Inputs: an unavailable environment and malformed configuration.
        Outputs: stable public failure reasons without installation or path exposure.

        Logic: simulate an import failure, then reject an unsupported setting.
        Dependencies: the interpreter probe, TOML parser, and launch spy.
        """
        with patch.object(web_runtime, "_python_ready", return_value="web_dependencies_missing"), patch.object(web_runtime, "_launch") as launched:
            result = web_runtime.ensure_web(self.data, static_dir=self.assets)
            self.assertEqual(result["reason"], "web_dependencies_missing")
            launched.assert_not_called()
        (self.data / "web.toml").write_text("# File purpose: Provide invalid synthetic settings.\n[web]\nport = true\n", encoding="utf-8")
        result = web_runtime.ensure_web(self.data, static_dir=self.assets)
        self.assertEqual(result["reason"], "web_config_invalid")
        self.assertNotIn(str(self.data), json.dumps(result))

    def test_startup_crash_returns_failure_without_a_ready_claim(self) -> None:
        """Inputs: a child that exits before publishing readiness.
        Outputs: an unavailable startup result and no ready description.

        Logic: inject a real short-lived child without loading optional frameworks.
        Dependencies: subprocess, ensure_web, and the synthetic UI inventory.
        """
        def failing_child(data_dir: Path, settings: dict) -> subprocess.Popen:
            """Inputs: ignored validated launch arguments. Outputs: an owned failing child.

            Logic: exit before registering any managed Web service.
            Dependencies: the current Python executable and subprocess.
            """
            return subprocess.Popen([sys.executable, "-c", "raise SystemExit(37)"],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        with patch.object(web_runtime, "_python_ready", return_value=None), patch.object(web_runtime, "_launch", side_effect=failing_child):
            result = web_runtime.ensure_web(self.data, static_dir=self.assets, timeout=2)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "startup_failed")
        self.assertFalse((self.data / ".web-runtime" / "runtime.json").exists())

    def test_runtime_symlinks_are_rejected_without_touching_the_target(self) -> None:
        """Inputs: a runtime directory replaced by a symbolic link.
        Outputs: a refusal and an unchanged unrelated target directory.

        Logic: reject the link before creating locks, logs, or private credentials.
        Dependencies: pathlib symlinks and the runtime path boundary.
        """
        target = self.base / "unrelated"
        target.mkdir()
        (self.data / ".web-runtime").symlink_to(target, target_is_directory=True)
        result = web_runtime.ensure_web(self.data, static_dir=self.assets)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(list(target.iterdir()), [])

    def test_stop_cannot_claim_success_without_a_description_while_server_lock_is_held(self) -> None:
        """Inputs: a held lifetime lock with missing instance registration.
        Outputs: an unavailable control result without any HTTP or PID action.

        Logic: distinguish an unregistered running child from an absent managed server.
        Dependencies: POSIX file locks and the safe shutdown status contract.
        """
        runtime = web_runtime._runtime_directory(self.data, create=True)
        with web_runtime._file_lock(runtime / "server.lock") as held:
            self.assertTrue(held)
            with patch.object(web_runtime, "_request") as requested:
                result = web_runtime.stop_web(self.data, timeout=0.2)
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["reason"], "startup_in_progress")
                requested.assert_not_called()
        self.assertEqual(web_runtime.stop_web(self.data)["status"], "stopped")

    def test_stop_serializes_with_a_startup_that_has_not_registered_its_child(self) -> None:
        """Inputs: a held startup coordinator before any server registration exists.
        Outputs: a bounded busy result rather than an incorrect stopped claim.

        Logic: wait on the same lock used by ensure before checking the lifetime lock.
        Dependencies: POSIX file locks and the shared startup deadline.
        """
        runtime = web_runtime._runtime_directory(self.data, create=True)
        with web_runtime._file_lock(runtime / "start.lock") as held:
            self.assertTrue(held)
            result = web_runtime.stop_web(self.data, timeout=0.1)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["reason"], "startup_busy")
        self.assertEqual(web_runtime.stop_web(self.data)["status"], "stopped")


@unittest.skipUnless(POSIX_AVAILABLE and WEB_AVAILABLE, "Install optional Web packages on POSIX to run process tests.")
class RuntimeProcessTests(unittest.TestCase):
    """Exercise real background servers against isolated synthetic workspaces."""

    def setUp(self) -> None:
        """Inputs: none. Outputs: isolated storage, resources, and cleanup tracking.

        Logic: initialize only synthetic state and explicitly use the test interpreter.
        Dependencies: tempfile, Coach, and make_assets.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.data = self.base / "private"
        self.coach = Coach(self.data / "coach.sqlite3")
        self.coach.initialize({"timezone": "UTC"})
        self.assets = make_assets(self.base / "assets")
        self.workspaces = [self.data]

    def tearDown(self) -> None:
        """Inputs: this test's managed workspaces. Outputs: stopped services and no files.

        Logic: use authenticated shutdown before deleting private runtime credentials.
        Dependencies: stop_web, Coach.close, and TemporaryDirectory.cleanup.
        """
        for directory in self.workspaces:
            result = web_runtime.stop_web(directory, timeout=5)
            self.assertEqual(result["status"], "stopped", result)
        self.coach.close()
        self.temp.cleanup()

    def start(self, directory: Path | None = None, port: int = 0) -> dict:
        """Inputs: an optional fixture authority and preferred port.
        Outputs: a verified actual managed server result.

        Logic: start or reuse through the same public runtime used by the CLI.
        Dependencies: ensure_web and the currently installed Web environment.
        """
        result = web_runtime.ensure_web(directory or self.data, python=sys.executable,
                                        static_dir=self.assets, preferred_port=port, timeout=10)
        self.assertEqual(result["status"], "ready", result)
        return result

    def description(self, directory: Path | None = None) -> dict:
        """Inputs: an optional fixture authority.
        Outputs: its private description for test-only ownership assertions.

        Logic: keep the token inside temporary fixtures and never print it.
        Dependencies: json and the private runtime file contract.
        """
        path = (directory or self.data) / ".web-runtime" / "runtime.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_start_reuse_status_and_safe_stop_hide_control_credentials(self) -> None:
        """Inputs: repeated calls for one initialized authority.
        Outputs: one reused live instance, private metadata, and graceful shutdown.

        Logic: check exact live identity and token absence from every public result.
        Dependencies: the managed child, local HTTP, and POSIX file modes.
        """
        first = self.start()
        description = self.description()
        again = self.start()
        status = web_runtime.web_status(self.data)
        self.assertEqual(first["action"], "started")
        self.assertEqual(again["action"], "reused")
        self.assertEqual(first["instance_id"], again["instance_id"])
        self.assertEqual(status["instance_id"], first["instance_id"])
        self.assertEqual((self.data / ".web-runtime").stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.data / ".web-runtime" / "runtime.json").stat().st_mode & 0o777, 0o600)
        self.assertNotIn(description["control_token"], json.dumps([first, again, status]))
        stopped = web_runtime.stop_web(self.data)
        self.assertEqual(stopped["status"], "stopped", stopped)
        self.assertFalse((self.data / ".web-runtime" / "runtime.json").exists())
        self.assertEqual(web_runtime.web_status(self.data)["status"], "stopped")

    def test_concurrent_start_requests_share_one_actual_instance(self) -> None:
        """Inputs: two simultaneous startup requests for one authority.
        Outputs: one started instance and one reuse of its exact identity.

        Logic: exercise startup serialization using independent worker calls.
        Dependencies: ThreadPoolExecutor and actual OS file locks.
        """
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(web_runtime.ensure_web, self.data, python=sys.executable,
                                    static_dir=self.assets, preferred_port=0, timeout=10) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual([result["status"] for result in results], ["ready", "ready"])
        self.assertEqual({result["action"] for result in results}, {"started", "reused"})
        self.assertEqual(len({result["instance_id"] for result in results}), 1)

    def test_occupied_unknown_port_is_left_untouched(self) -> None:
        """Inputs: a preferred port already owned by an unrelated local listener.
        Outputs: a ready server on another port and an unchanged original listener.

        Logic: let the child bind atomically instead of killing the occupying process.
        Dependencies: sockets and the server's fallback port allocation.
        """
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            occupied = listener.getsockname()[1]
            result = self.start(port=occupied)
            self.assertNotEqual(self.description()["port"], occupied)
            self.assertEqual(listener.getsockname()[1], occupied)
            self.assertEqual(result["status"], "ready")

    def test_copied_store_and_runtime_file_cannot_reuse_or_stop_the_original(self) -> None:
        """Inputs: a database backup with the original workspace ID and runtime copy.
        Outputs: a distinct store and instance while the original service stays ready.

        Logic: reject path-distinct copies before sending a private control request.
        Dependencies: Coach backup, location-bound store identity, and live probes.
        """
        original = self.start()
        clone = self.base / "clone"
        clone.mkdir()
        self.coach.backup(clone / "coach.sqlite3")
        self.workspaces.append(clone)
        runtime = web_runtime._runtime_directory(clone, create=True)
        shutil.copyfile(self.data / ".web-runtime" / "runtime.json", runtime / "runtime.json")
        stopped_copy = web_runtime.stop_web(clone)
        self.assertEqual(stopped_copy["status"], "stopped")
        duplicate = self.start(clone, port=self.description()["port"])
        self.assertEqual(original["workspace_id"], duplicate["workspace_id"])
        self.assertNotEqual(original["store_id"], duplicate["store_id"])
        self.assertNotEqual(original["instance_id"], duplicate["instance_id"])
        self.assertEqual(web_runtime.web_status(self.data)["instance_id"], original["instance_id"])

    def test_crash_leaves_stale_metadata_that_can_be_recovered(self) -> None:
        """Inputs: an owned test server killed before its cleanup handler runs.
        Outputs: a new instance after stale registration recovery.

        Logic: kill only the process created by this fixture, then use public startup.
        Dependencies: POSIX signals, lifetime lock release, and actual managed metadata.
        """
        first = self.start()
        description = self.description()
        os.kill(description["pid"], signal.SIGKILL)
        deadline = time.monotonic() + 3
        while web_runtime._server_locked(self.data / ".web-runtime") and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(web_runtime._server_locked(self.data / ".web-runtime"))
        self.assertTrue((self.data / ".web-runtime" / "runtime.json").exists())
        next_instance = self.start()
        self.assertNotEqual(next_instance["instance_id"], first["instance_id"])

    def test_unresponsive_lifetime_lock_does_not_start_a_second_server(self) -> None:
        """Inputs: an owned runtime lock with no responsive managed API.
        Outputs: an unavailable result and no replacement launch.

        Logic: refuse duplicate startup while the prior managed process still owns its lock.
        Dependencies: OS locks, private metadata, and a bounded failed live probe.
        """
        runtime = web_runtime._runtime_directory(self.data, create=True)
        identity = workspace_identity(self.data)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            description = {"service": SERVICE_NAME, "runtime_protocol": RUNTIME_PROTOCOL,
                           **identity, "port": listener.getsockname()[1], "instance_id": "synthetic-live-lock",
                           "control_token": "synthetic-private-control-token"}
            web_runtime._write_descriptor(runtime, description)
            with web_runtime._file_lock(runtime / "server.lock") as held:
                self.assertTrue(held)
                with patch.object(web_runtime, "_launch") as launched:
                    result = web_runtime.ensure_web(self.data, python=sys.executable,
                                                    static_dir=self.assets, timeout=0.2)
                    self.assertEqual(result["reason"], "runtime_unresponsive")
                    launched.assert_not_called()

    def test_damaged_ui_is_not_ready_but_owned_shutdown_still_works(self) -> None:
        """Inputs: resources damaged after a successful managed startup.
        Outputs: readiness refusal and successful authenticated shutdown.

        Logic: keep instance control independent from the page's readiness condition.
        Dependencies: live resource verification and the private shutdown endpoint.
        """
        self.start()
        (self.assets / "index.html").write_text("damaged", encoding="utf-8")
        status = web_runtime.web_status(self.data)
        self.assertEqual(status["reason"], "runtime_not_ready")
        self.assertEqual(web_runtime.stop_web(self.data)["status"], "stopped")

    def test_unavailable_database_is_not_ready_but_owned_shutdown_still_works(self) -> None:
        """Inputs: an owned server whose existing database becomes unavailable.
        Outputs: unavailable readiness, retained ownership, and safe graceful shutdown.

        Logic: never recreate the database; stop using the private path-bound instance.
        Dependencies: managed fallback identity and authenticated runtime control.
        """
        first = self.start()
        description = self.description()
        self.coach.close()
        database = self.data / "coach.sqlite3"
        hidden = self.data / "temporarily-held.sqlite3"
        database.rename(hidden)
        try:
            self.assertEqual(web_runtime.web_status(self.data)["status"], "unavailable")
            actual = web_runtime._request(description["port"], "/v1/runtime", 2)
            self.assertIsNotNone(actual)
            self.assertIs(actual["database_ready"], False)
            self.assertEqual(actual["store_id"], first["store_id"])
            self.assertEqual(web_runtime.stop_web(self.data)["status"], "stopped")
            self.assertFalse(database.exists())
        finally:
            hidden.rename(database)

    def test_missing_database_and_copied_runtime_cannot_stop_the_original(self) -> None:
        """Inputs: a copied private description at a different location with no database.
        Outputs: a control refusal while the original owned service stays ready.

        Logic: validate the description's canonical store binding before using its token.
        Dependencies: canonical path identity and safe private shutdown discovery.
        """
        original = self.start()
        clone = self.base / "missing-copy"
        clone.mkdir()
        runtime = web_runtime._runtime_directory(clone, create=True)
        shutil.copyfile(self.data / ".web-runtime" / "runtime.json", runtime / "runtime.json")
        refused = web_runtime.stop_web(clone)
        self.assertEqual(refused["status"], "unavailable")
        self.assertEqual(refused["reason"], "runtime_identity_mismatch")
        self.assertEqual(web_runtime.web_status(self.data)["instance_id"], original["instance_id"])


if __name__ == "__main__":
    unittest.main()
