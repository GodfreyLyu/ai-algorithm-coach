"""Exercise command line and standalone Skill behavior outside the source tree."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "skills" / "algorithm-coach" / "scripts" / "coach.py"


class CommandTests(unittest.TestCase):
    """Test public commands with synthetic data in child processes."""

    def _run(self, entry: Path, directory: Path, arguments: list[str],
             expected_code: int = 0) -> dict:
        """Run a Skill entry point and decode its output.

        Inputs: An entry path, private data path, arguments, and expected exit code.
        Outputs: Parsed JSON from stdout.
        Logic: Start a fresh process outside the checkout and use no site packages.
        Dependencies: subprocess, Python, and the Skill runner.
        """
        process = subprocess.run(
            [sys.executable, "-S", str(entry), "--data-dir", str(directory), *arguments],
            cwd=directory.parent, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(process.returncode, expected_code, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def test_standalone_bundle_can_save_read_and_reuse_feedback(self) -> None:
        """Prove the distributed Skill works without the repository on its import path.

        Inputs: A fresh bundle and a private temporary data directory.
        Outputs: A saved receipt, retained history, and a valid next plan.
        Logic: Build a bundle, run it elsewhere, and inspect the completed feedback loop.
        Dependencies: The bundle builder, subprocess, and the stdlib-only core.
        """
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            bundle = base / "algorithm-coach"
            built = subprocess.run([sys.executable, "-S", str(ROOT / "scripts" / "build_skill.py"),
                                    "--output", str(bundle)], capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            entry = bundle / "scripts" / "coach.py"
            data = base / "private"
            self.assertTrue(self._run(entry, data, ["init"])["ok"])
            plan = self._run(entry, data, ["plan", "--date", "2026-01-01"])["data"]
            item = plan["items"][0]
            request = ["feedback", "--attempt", item["attempt_id"], "--submission", "synthetic-submit",
                       "--expected-revision", "0", "--changes", '{"result":"B","elapsed_minutes":25}',
                       "--occurred-at", "2026-01-01T12:00:00+00:00"]
            receipt = self._run(entry, data, request)["data"]
            self.assertEqual(receipt["status"], "applied")
            self.assertEqual(receipt, self._run(entry, data, request)["data"])
            fetched = self._run(entry, data, ["receipt", "--submission", "synthetic-submit"])["data"]
            self.assertEqual(receipt, fetched)
            history = self._run(entry, data, ["history", "--attempt", item["attempt_id"]])["data"]
            self.assertEqual(history["attempt"]["feedback"]["result"], "B")
            following = self._run(entry, data, ["plan", "--date", "2026-01-02"])["data"]
            self.assertTrue(any(row["reason"] == "retest" for row in following["items"]))

    def test_cli_returns_validation_error_for_non_object_changes(self) -> None:
        """Return structured errors instead of accepting malformed changes.

        Inputs: A feedback command containing a JSON array.
        Outputs: A validation error and nonzero exit code.
        Logic: Parse the payload before any feedback is written.
        Dependencies: subprocess and the public CLI.
        """
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "private"
            self._run(ENTRY, data, ["init"])
            error = self._run(ENTRY, data, ["feedback", "--attempt", "synthetic", "--submission", "invalid",
                                           "--expected-revision", "0", "--changes", "[]"], expected_code=1)
            self.assertFalse(error["ok"])
            self.assertEqual(error["error"]["code"], "validation_error")

    def test_read_does_not_create_missing_state(self) -> None:
        """Keep reads from silently initializing a different authority.

        Inputs: A read command against a missing private directory.
        Outputs: An error and no created directory.
        Logic: Require explicit initialization before using state.
        Dependencies: The Skill runner and Coach lazy connections.
        """
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "not-created"
            self._run(ENTRY, data, ["state"], expected_code=1)
            self.assertFalse(data.exists())

    def test_environment_path_avoids_daily_reconfiguration(self) -> None:
        """Allow one persistent data path setting for later commands.

        Inputs: A data path set through the documented environment value.
        Outputs: A successful initialization with no command line path.
        Logic: Supply the environment only to an isolated child process.
        Dependencies: subprocess and CLI environment lookup.
        """
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "private"
            environment = dict(os.environ, ALGORITHM_COACH_DATA_DIR=str(data))
            process = subprocess.run([sys.executable, "-S", str(ENTRY), "init"], env=environment,
                                     capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertTrue(json.loads(process.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
