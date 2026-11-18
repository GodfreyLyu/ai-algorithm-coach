"""Exercise command line and standalone Skill behavior outside the source tree."""

import json
import os
from pathlib import Path
import sqlite3
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
            self.assertFalse((bundle / "lib" / "algorithm_coach" / "legacy_import.py").exists())
            self.assertTrue(self._run(entry, data, ["init"])["ok"])
            connection = sqlite3.connect(data / "coach.sqlite3")
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
                self.assertIn("learning_checkpoints", tables)
                self.assertIn("history_evidence", tables)
                self.assertFalse(any(name.startswith("legacy_") for name in tables))
            finally:
                connection.close()
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
            problem_history = self._run(entry, data, ["history", "--problem", item["problem"]["id"]])["data"]
            self.assertEqual(problem_history["problem_id"], item["problem"]["id"])
            self.assertEqual(problem_history["attempts"][0]["attempt"]["id"], item["attempt_id"])
            self.assertEqual(problem_history["evidence"], [])
            following = self._run(entry, data, ["plan", "--date", "2026-01-02"])["data"]
            self.assertTrue(any(row["reason"] == "retest" for row in following["items"]))
            self.assertTrue((bundle / "references" / "policies.md").is_file())
            policy_file = base / "scope.toml"
            policy_file.write_text(
                '# Describe a synthetic temporary scope.\nname = "Trees"\n'
                'topics_any = ["tree"]\ndifficulties = ["easy"]\n'
                'max_daily_count = 2\neffective_from = "2026-01-03"\n', encoding="utf-8")
            proposed = self._run(entry, data, ["policy", "propose", "--file", str(policy_file),
                                               "--expected-revision", "0", "--submission", "bundle-proposal"])["data"]
            preview = self._run(entry, data, ["policy", "preview", "--proposal", proposed["proposal_id"]])["data"]
            self.assertFalse(preview["stale"])
            self.assertGreater(preview["eligible_count"], 0)
            applied = self._run(entry, data, ["policy", "activate", "--proposal", proposed["proposal_id"],
                                             "--expected-revision", "0", "--accept-hash", proposed["content_hash"],
                                             "--submission", "bundle-activation"])["data"]
            self.assertEqual(applied["status"], "applied")
            scoped = self._run(entry, data, ["plan", "--date", "2026-01-03"])["data"]
            self.assertLessEqual(len(scoped["items"]), 2)
            self.assertTrue(all("tree" in row["problem"]["tags"] for row in scoped["items"]))

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

    def test_cli_imports_toml_metadata_and_reports_capabilities(self) -> None:
        """Read a metadata-only TOML document through the public command line.

        Inputs: A temporary import document and an initialized local workspace.
        Outputs: An applied import and newly selectable metadata.
        Logic: Parse the same envelope that the documented example uses.
        Dependencies: The Skill runner, TOML parsing, and catalog validation.
        """
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            data = base / "private"
            self._run(ENTRY, data, ["init"])
            document = base / "metadata.toml"
            document.write_text(
                '# Describe a synthetic test import.\n[[problems]]\nid = "leetcode:27"\n'
                'title = "Remove Element"\ndifficulty = "easy"\n'
                'tags = ["array", "two-pointers"]\n'
                'url = "https://leetcode.com/problems/remove-element/"\n', encoding="utf-8")
            result = self._run(ENTRY, data, ["catalog", "import", "--file", str(document),
                                             "--submission", "cli-import"])["data"]
            self.assertEqual(result["added_count"], 1)
            catalog = self._run(ENTRY, data, ["catalog"])["data"]
            self.assertIn("leetcode:27", [row["id"] for row in catalog["problems"]])
            self.assertTrue(self._run(ENTRY, data, ["capabilities"])["ok"])

    def test_duplicate_json_fields_are_not_silently_overwritten(self) -> None:
        """Reject ambiguous input before any learning record is changed.

        Inputs: A changes object that reports two mutually exclusive results.
        Outputs: A structured validation error.
        Logic: Preserve the exact meaning of a submitted operation.
        Dependencies: The strict CLI JSON reader.
        """
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "private"
            self._run(ENTRY, data, ["init"])
            result = self._run(ENTRY, data, ["feedback", "--attempt", "synthetic", "--submission", "ambiguous",
                                            "--expected-revision", "0", "--changes", '{"result":"A","result":"C"}'],
                               expected_code=1)
            self.assertEqual(result["error"]["code"], "validation_error")

    def test_conversion_commands_are_not_runtime_capabilities(self) -> None:
        """Reject conversion requests without touching a supplied data directory.

        Inputs: Removed command names and a missing synthetic workspace.
        Outputs: Parser errors and no filesystem initialization.
        Logic: Keep format maintenance outside the public command surface.
        Dependencies: subprocess and the Skill entry point.
        """
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "not-created"
            for command in ("legacy", "migrate"):
                result = subprocess.run(
                    [sys.executable, "-S", str(ENTRY), "--data-dir", str(data), command],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 2)
                self.assertFalse(data.exists())


if __name__ == "__main__":
    unittest.main()
