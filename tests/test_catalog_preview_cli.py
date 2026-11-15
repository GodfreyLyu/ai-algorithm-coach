"""Verify public metadata preview and import commands outside the source tree."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "skills" / "algorithm-coach" / "scripts" / "coach.py"


def metadata(number: int = 900001) -> dict:
    """Build a synthetic five-field problem record.

    Inputs: A positive synthetic problem number.
    Outputs: An independent metadata object with a canonical URL shape.
    Logic: Use public-shaped metadata without asserting that its page exists.
    Dependencies: No website, model, or user training records.
    """
    return {"id": f"leetcode:{number}", "title": f"Synthetic Array Exercise {number}",
            "difficulty": "easy", "tags": ["two-pointers", "array"],
            "url": f"https://leetcode.com/problems/synthetic-array-exercise-{number}/"}


class CatalogPreviewCommandTests(unittest.TestCase):
    """Exercise the standard-library CLI and fresh standalone Skill bundles."""

    def setUp(self) -> None:
        """Create a synthetic workspace outside the checkout.

        Inputs: None.
        Outputs: A temporary initialized UTC workspace and public runner path.
        Logic: Keep every command isolated from private user records and Web services.
        Dependencies: tempfile and the public init command.
        """
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.data = self.base / "private"
        self.entry = ENTRY
        self._run(["init", "--timezone", "UTC", "--language", "Java"])

    def tearDown(self) -> None:
        """Remove this test's temporary metadata and records.

        Inputs: The isolated fixture.
        Outputs: No retained test files.
        Logic: Every CLI child closes SQLite before cleanup.
        Dependencies: TemporaryDirectory.cleanup.
        """
        self.temporary.cleanup()

    def _run(self, arguments: list[str], expected_code: int = 0,
             directory: Path | None = None) -> dict:
        """Execute one public Skill command without site packages.

        Inputs: CLI arguments, expected exit code, and optional workspace override.
        Outputs: The parsed structured response.
        Logic: Run from outside the checkout and pass paths as argument values.
        Dependencies: subprocess, the public runner, and Python's standard library.
        """
        process = subprocess.run(
            [sys.executable, "-S", str(self.entry), "--data-dir", str(directory or self.data), *arguments],
            cwd=self.base, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(process.returncode, expected_code, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["ok"], expected_code == 0, result)
        return result

    def _write_json(self, name: str, document: object) -> Path:
        """Write a synthetic metadata document for a CLI test.

        Inputs: A local fixture name and JSON-compatible content.
        Outputs: Its absolute temporary path.
        Logic: Keep source reports and malformed fixtures outside the maintained tree.
        Dependencies: pathlib and json.
        """
        path = self.base / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def _write_toml(self, name: str, problems: list[dict]) -> Path:
        """Write equivalent five-field TOML metadata.

        Inputs: A temporary filename and simple synthetic problem objects.
        Outputs: A TOML document using repeated problems tables.
        Logic: Encode basic strings and lists with compatible JSON literal syntax.
        Dependencies: pathlib and json; fixture values contain no exotic escapes.
        """
        lines = ["# File purpose: Provide synthetic CLI metadata for an isolated test."]
        for problem in problems:
            lines.append("[[problems]]")
            for key, value in problem.items():
                lines.append(f"{key} = {json.dumps(value)}")
        path = self.base / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _snapshot(self) -> dict:
        """Capture the private fixture's complete file inventory.

        Inputs: The initialized synthetic data directory.
        Outputs: Relative paths mapped to contents and modification timestamps.
        Logic: Detect database changes, side files, and unexpected runtime startup.
        Dependencies: pathlib and closed CLI SQLite connections.
        """
        return {path.relative_to(self.data).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.data.rglob("*") if path.is_file()}

    def _build_bundle(self) -> Path:
        """Build and select a fresh dependency-free standalone Skill.

        Inputs: The current source checkout and this test's temporary directory.
        Outputs: The standalone bundle path, also used by later commands.
        Logic: Copy only the public core bundle and execute its own runner afterward.
        Dependencies: build_skill.py and Python without site packages.
        """
        bundle = self.base / "algorithm-coach"
        built = subprocess.run(
            [sys.executable, "-S", str(ROOT / "scripts" / "build_skill.py"), "--output", str(bundle)],
            cwd=self.base, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        self.assertTrue(json.loads(built.stdout)["ok"])
        self.entry = bundle / "scripts" / "coach.py"
        return bundle

    def test_json_and_toml_share_preview_identity_and_exact_import_receipt(self) -> None:
        """Preview and import equivalent documents with one normalized identity.

        Inputs: JSON and TOML containing equivalent reordered and padded metadata.
        Outputs: One added problem, an exact replay receipt, and normalized readback.
        Logic: Match the preview hash to the committed receipt across both formats.
        Dependencies: The public catalog preview, import, receipt, and read commands.
        """
        first = metadata()
        second = deepcopy(first)
        second["title"] = "  " + first["title"] + "  "
        second["tags"].reverse()
        json_file = self._write_json("candidate.json", {"problems": [first]})
        toml_file = self._write_toml("candidate.toml", [second])
        before = self._snapshot()
        json_preview = self._run(["catalog", "preview", "--file", str(json_file)])["data"]
        toml_preview = self._run(["catalog", "preview", "--file", str(toml_file)])["data"]
        self.assertEqual(self._snapshot(), before)
        self.assertTrue(json_preview["metadata_valid"])
        self.assertTrue(json_preview["import_allowed"])
        self.assertEqual(json_preview["payload_hash"], toml_preview["payload_hash"])
        self.assertEqual(json_preview["normalized_problems"], toml_preview["normalized_problems"])
        self.assertEqual(len(json_preview["new_problems"]), 1)
        self.assertEqual(json_preview["unchanged_problems"], [])
        self.assertEqual(json_preview["conflicts"], [])
        imported = self._run(["catalog", "import", "--file", str(json_file), "--submission", "synthetic-json-import",
                              "--expected-hash", json_preview["payload_hash"]])["data"]
        self.assertEqual(imported["status"], "applied")
        self.assertEqual(imported["operation"], "import_catalog")
        self.assertEqual(imported["payload_hash"], json_preview["payload_hash"])
        self.assertEqual(imported["added_count"], 1)
        replay = self._run(["catalog", "import", "--file", str(toml_file), "--submission", "synthetic-json-import",
                            "--expected-hash", toml_preview["payload_hash"]])["data"]
        self.assertEqual(replay, imported)
        self.assertEqual(self._run(["receipt", "--submission", "synthetic-json-import"])["data"], imported)
        current = self._run(["catalog"])["data"]
        saved = next(problem for problem in current["problems"] if problem["id"] == first["id"])
        self.assertEqual(saved, json_preview["normalized_problems"][0])
        unchanged = self._run(["catalog", "preview", "--file", str(toml_file)])["data"]
        self.assertEqual(unchanged["new_problems"], [])
        self.assertEqual(unchanged["unchanged_problems"], [saved])
        no_change = self._run(["catalog", "import", "--file", str(toml_file), "--submission", "synthetic-toml-noop"])["data"]
        self.assertEqual(no_change["added_count"], 0)
        self.assertEqual(no_change["catalog_version"], imported["catalog_version"])
        self.assertEqual(no_change["state_version"], imported["state_version"])

    def test_invalid_documents_fail_without_writing(self) -> None:
        """Reject ambiguous envelopes, fields, labels, identities, and links.

        Inputs: Synthetic invalid metadata documents in the public file format.
        Outputs: Validation errors for preview and import with unchanged storage.
        Logic: Refuse the whole file without retaining a receipt or partial records.
        Dependencies: Strict JSON parsing, metadata validation, and public CLI commands.
        """
        item = metadata()
        invalid = [
            [item], {"problems": [item], "source": "https://example.test/"},
            {"problems": [item, item]}, {"problems": []}, {"problems": {}},
            {"problems": [{**item, "source": "https://example.test/"}]},
            {"problems": [{**item, "statement": "Synthetic forbidden text."}]},
            {"problems": [{**item, "id": "leetcode:0900001"}]},
            {"problems": [{**item, "difficulty": "Easy"}]},
            {"problems": [{**item, "tags": ["Graph"]}]},
            {"problems": [{**item, "tags": ["two_pointers"]}]},
            {"problems": [{**item, "tags": ["array", "array"]}]},
            {"problems": [{**item, "url": "http://leetcode.com/problems/synthetic/"}]},
            {"problems": [{**item, "url": "https://leetcode.com.evil.test/problems/synthetic/"}]},
            {"problems": [{**item, "url": "https://leetcode.com/problems/synthetic/?secret=fixture"}]},
        ]
        before = self._snapshot()
        for index, document in enumerate(invalid):
            with self.subTest(index=index):
                file = self._write_json(f"invalid-{index}.json", document)
                for command in ("preview", "import"):
                    arguments = ["catalog", command, "--file", str(file)]
                    if command == "import":
                        arguments.extend(["--submission", f"synthetic-invalid-{index}"])
                    result = self._run(arguments, expected_code=1)
                    self.assertEqual(result["error"]["code"], "validation_error")
                self.assertEqual(self._snapshot(), before)
        duplicate = self.base / "duplicate-fields.json"
        duplicate.write_text('{"problems": [], "problems": ' + json.dumps([item]) + '}', encoding="utf-8")
        rejected = self._run(["catalog", "preview", "--file", str(duplicate)], expected_code=1)
        self.assertEqual(rejected["error"]["code"], "validation_error")
        self.assertEqual(self._snapshot(), before)

    def test_preview_refuses_missing_database_without_creating_workspace(self) -> None:
        """Keep read-only preview from implicitly initializing storage.

        Inputs: A valid document and absent directory or database file.
        Outputs: A not-initialized error with no created database or runtime files.
        Logic: Require the caller's existing authority even for a valid import preview.
        Dependencies: The public preview command and filesystem inspection.
        """
        file = self._write_json("missing-store.json", {"problems": [metadata()]})
        missing = self.base / "missing"
        rejected = self._run(["catalog", "preview", "--file", str(file)], expected_code=1, directory=missing)
        self.assertEqual(rejected["error"]["code"], "not_initialized")
        self.assertFalse(missing.exists())
        missing.mkdir()
        self._run(["catalog", "preview", "--file", str(file)], expected_code=1, directory=missing)
        self.assertEqual(list(missing.iterdir()), [])

    def test_hash_guard_rejects_changed_file_and_submission_content_conflicts(self) -> None:
        """Bind actual submissions to their preview without changing retry identity.

        Inputs: A previewed file that changes, followed by a reused operation ID.
        Outputs: Guard and idempotency conflicts without unintended writes.
        Logic: Reject changed payloads before confirming any import receipt.
        Dependencies: Normalized payload hashes, permanent receipts, and the CLI.
        """
        original = metadata()
        file = self._write_json("guarded.json", {"problems": [original]})
        preview = self._run(["catalog", "preview", "--file", str(file)])["data"]
        before = self._snapshot()
        changed = {**original, "title": "Synthetic Changed Title"}
        self._write_json(file.name, {"problems": [changed]})
        rejected = self._run(["catalog", "import", "--file", str(file), "--submission", "synthetic-guarded",
                              "--expected-hash", preview["payload_hash"]], expected_code=1)
        self.assertEqual(rejected["error"]["code"], "content_hash_mismatch")
        self.assertEqual(self._snapshot(), before)
        self._run(["receipt", "--submission", "synthetic-guarded"], expected_code=1)
        self._write_json(file.name, {"problems": [original]})
        imported = self._run(["catalog", "import", "--file", str(file), "--submission", "synthetic-guarded",
                              "--expected-hash", preview["payload_hash"]])["data"]
        self.assertEqual(imported["payload_hash"], preview["payload_hash"])
        after = self._snapshot()
        self._write_json(file.name, {"problems": [changed]})
        rejected = self._run(["catalog", "import", "--file", str(file), "--submission", "synthetic-guarded"], expected_code=1)
        self.assertEqual(rejected["error"]["code"], "idempotency_conflict")
        self.assertEqual(self._snapshot(), after)

    def test_conflicting_preview_reports_all_items_and_import_refuses_entire_batch(self) -> None:
        """Keep preview classification separate from execution success.

        Inputs: One new record mixed with an existing conflicting problem ID.
        Outputs: A readable blocked preview and an atomically rejected import.
        Logic: Report the conflict without dropping it and importing only the new item.
        Dependencies: Existing catalog metadata and public preview/import commands.
        """
        stored = self._run(["catalog"])["data"]["problems"][0]
        changed = {**stored, "title": "Synthetic Conflicting Existing Title"}
        file = self._write_json("mixed-conflict.json", {"problems": [metadata(), changed]})
        before = self._snapshot()
        preview = self._run(["catalog", "preview", "--file", str(file)])["data"]
        self.assertTrue(preview["metadata_valid"])
        self.assertFalse(preview["import_allowed"])
        self.assertEqual(len(preview["new_problems"]), 1)
        self.assertEqual(preview["conflicts"][0]["problem_id"], stored["id"])
        self.assertIn("title", preview["conflicts"][0]["fields"])
        self.assertEqual(preview["blockers"][0]["code"], "catalog_conflict")
        self.assertEqual(self._snapshot(), before)
        rejected = self._run(["catalog", "import", "--file", str(file), "--submission", "synthetic-mixed-conflict",
                              "--expected-hash", preview["payload_hash"]], expected_code=1)
        self.assertEqual(rejected["error"]["code"], "catalog_conflict")
        self.assertEqual(self._snapshot(), before)
        self._run(["receipt", "--submission", "synthetic-mixed-conflict"], expected_code=1)

    def test_standalone_import_can_feed_later_scoped_plans_without_rewriting_history(self) -> None:
        """Run the complete import workflow through a fresh standalone Skill.

        Inputs: Synthetic metadata, an existing plan and feedback, and a future scope.
        Outputs: Readable import receipts, preserved history, and a valid later selection.
        Logic: Use only public commands with site packages disabled outside the checkout.
        Dependencies: Bundle creation, CLI policy operations, and shared deterministic rules.
        """
        bundle = self._build_bundle()
        self.assertTrue((bundle / "references" / "policies.md").is_file())
        self.assertTrue((bundle / "references" / "catalog-discovery.md").is_file())
        capabilities = self._run(["capabilities"])["data"]
        self.assertFalse(capabilities["supports"]["remote_fetch"])
        self.assertTrue(capabilities["supports"]["metadata_import_preview"])
        self.assertTrue(capabilities["supports"]["metadata_import_hash_guard"])
        plan = self._run(["plan", "--date", "2026-01-01"])["data"]
        first = plan["items"][0]
        saved = self._run(["feedback", "--attempt", first["attempt_id"], "--submission", "synthetic-existing-feedback",
                           "--expected-revision", "0", "--changes", '{"result":"B","elapsed_minutes":20}',
                           "--occurred-at", "2026-01-01T12:00:00+00:00"])["data"]
        frozen = self._run(["show", "--date", "2026-01-01"])["data"]
        history = self._run(["history", "--attempt", first["attempt_id"]])["data"]
        file = self._write_toml("standalone-candidates.toml", [metadata()])
        before = self._snapshot()
        preview = self._run(["catalog", "preview", "--file", str(file)])["data"]
        self.assertEqual(self._snapshot(), before)
        request = ["catalog", "import", "--file", str(file), "--submission", "synthetic-standalone-import",
                   "--expected-hash", preview["payload_hash"]]
        receipt = self._run(request)["data"]
        self.assertEqual(receipt["status"], "applied")
        self.assertEqual(self._run(request)["data"], receipt)
        self.assertEqual(self._run(["receipt", "--submission", receipt["submission_id"]])["data"], receipt)
        catalog = self._run(["catalog"])["data"]
        self.assertIn(preview["normalized_problems"][0], catalog["problems"])
        self.assertEqual(self._run(["show", "--date", "2026-01-01"])["data"], frozen)
        self.assertEqual(self._run(["history", "--attempt", first["attempt_id"]])["data"], history)
        self.assertEqual(self._run(["receipt", "--submission", saved["submission_id"]])["data"], saved)
        proposal = self._run(["policy", "propose", "--changes", json.dumps({
            "effective_from": "2026-01-02", "topics_any": ["array"], "difficulties": ["easy"],
            "problem_ids": [metadata()["id"]],
        }), "--expected-revision", "0", "--submission", "synthetic-future-scope"])["data"]
        scope_preview = self._run(["policy", "preview", "--proposal", proposal["proposal_id"]])["data"]
        self.assertTrue(scope_preview["activation_allowed"])
        self._run(["policy", "activate", "--proposal", proposal["proposal_id"], "--expected-revision", "0",
                   "--accept-hash", proposal["content_hash"], "--submission", "synthetic-approved-scope"])
        later = self._run(["plan", "--date", "2026-01-02"])["data"]
        self.assertEqual(len(later["items"]), 1)
        self.assertEqual(later["items"][0]["problem"]["id"], metadata()["id"])
        retained = self._run(["show", "--date", "2026-01-01"])["data"]
        # Current policy diagnostics can change without rewriting the frozen plan.
        self.assertEqual({key: value for key, value in retained.items() if not key.startswith("current_policy")},
                         {key: value for key, value in frozen.items() if not key.startswith("current_policy")})
        self.assertEqual(self._run(["history", "--attempt", first["attempt_id"]])["data"], history)
        self.assertFalse((self.data / ".web-runtime").exists())


if __name__ == "__main__":
    unittest.main()
