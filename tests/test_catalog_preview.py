"""Verify read-only catalog previews, guarded imports, and preserved training history."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.errors import CoachError
from algorithm_coach.service import Coach


def metadata(identifier: int = 990001) -> dict:
    """Build a synthetic five-field metadata candidate.

    Inputs: An unused numeric problem identifier.
    Outputs: Independent metadata with an official-shaped synthetic link.
    Logic: Provide only bounded public-style fields without asserting remote truth.
    Dependencies: Python string formatting. No source page is fetched.
    """
    return {"id": f"leetcode:{identifier}", "title": f"Synthetic Catalog Case {identifier}",
            "difficulty": "easy", "tags": ["array", "two-pointers"],
            "url": f"https://leetcode.com/problems/synthetic-catalog-case-{identifier}/"}


class CatalogPreviewTests(unittest.TestCase):
    """Inspect temporary stores through the public catalog service contract."""

    def setUp(self) -> None:
        """Create an initialized synthetic workspace outside the checkout.

        Inputs: None.
        Outputs: An isolated Coach and its private database path.
        Logic: Initialize UTC training with no imported personal records.
        Dependencies: tempfile, pathlib, and Coach.
        """
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "private" / "coach.sqlite3"
        self.coach = Coach(self.database)
        self.coach.initialize({"timezone": "UTC", "language": "Java"})

    def tearDown(self) -> None:
        """Close the fixture before removing its synthetic records.

        Inputs: The isolated Coach and temporary directory.
        Outputs: No open connection or retained fixture files.
        Logic: Discard only data created by this test.
        Dependencies: Coach.close and TemporaryDirectory.cleanup.
        """
        self.coach.close()
        self.temporary.cleanup()

    def test_preview_classifies_every_id_and_reports_all_conflicts(self) -> None:
        """Preview a mixed batch without silently dropping blocked entries.

        Inputs: New, identical, and two conflicting problem IDs.
        Outputs: Complete classifications, field differences, and a refused batch.
        Logic: Normalize both sides while preserving every incoming candidate.
        Dependencies: Stored metadata, preview_catalog, and deepcopy.
        """
        catalog = self.coach.list_problems()
        identical = deepcopy(catalog["problems"][0])
        identical["tags"].reverse()
        conflict_one = {**deepcopy(catalog["problems"][1]), "title": "Synthetic replacement title"}
        conflict_two = deepcopy(catalog["problems"][2])
        conflict_two["difficulty"] = "hard" if conflict_two["difficulty"] != "hard" else "easy"
        new = metadata()
        new["tags"] = ["synthetic-training-topic", "array"]
        batch = [conflict_two, new, identical, conflict_one]
        original = deepcopy(batch)
        result = self.coach.preview_catalog(batch)
        self.assertTrue(result["metadata_valid"])
        self.assertFalse(result["import_allowed"])
        self.assertEqual(result["catalog_version"], catalog["catalog_version"])
        self.assertEqual([row["id"] for row in result["new_problems"]], [new["id"]])
        self.assertEqual([row["id"] for row in result["unchanged_problems"]], [identical["id"]])
        conflicts = {row["problem_id"]: row for row in result["conflicts"]}
        self.assertEqual(conflicts[conflict_one["id"]]["fields"], ["title"])
        self.assertEqual(conflicts[conflict_two["id"]]["fields"], ["difficulty"])
        self.assertEqual(conflicts[conflict_one["id"]]["incoming"]["title"], conflict_one["title"])
        self.assertNotEqual(conflicts[conflict_one["id"]]["existing"]["title"], conflict_one["title"])
        self.assertEqual(set(result["blockers"][0]["details"]["problem_ids"]), set(conflicts))
        self.assertEqual(result["unknown_tags"], ["synthetic-training-topic"])
        self.assertEqual(len(result["normalized_problems"]), len(batch))
        self.assertEqual(batch, original)

    def test_preview_is_read_only_with_existing_plan_and_feedback(self) -> None:
        """Use SQLite query-only mode to prove preview has no write side effects.

        Inputs: A frozen plan, retained feedback, and one candidate batch.
        Outputs: Unchanged database bytes, rows, versions, receipts, and connection changes.
        Logic: Preview under a write prohibition and compare the entire saved store.
        Dependencies: Coach, SQLite query_only, and synthetic training records.
        """
        plan = self.coach.ensure_plan("2026-01-01")
        item = plan["items"][0]
        self.coach.submit_feedback(item["attempt_id"], "synthetic-existing-feedback", 0,
                                   {"result": "D", "elapsed_minutes": 20},
                                   occurred_at="2026-01-01T12:00:00+00:00")
        connection = self.coach._db()
        before_rows = list(connection.iterdump())
        before_bytes = self.database.read_bytes()
        before_changes = connection.total_changes
        before_files = sorted(path.name for path in self.database.parent.iterdir())
        connection.execute("PRAGMA query_only = ON")
        try:
            first = self.coach.preview_catalog([metadata()])
            second = self.coach.preview_catalog([metadata()])
            self.assertEqual(first, second)
            self.assertFalse(connection.in_transaction)
            self.assertEqual(connection.total_changes, before_changes)
            self.assertEqual(list(connection.iterdump()), before_rows)
            self.assertEqual(self.database.read_bytes(), before_bytes)
            self.assertEqual(sorted(path.name for path in self.database.parent.iterdir()), before_files)
        finally:
            connection.execute("PRAGMA query_only = OFF")

    def test_preview_does_not_finish_a_callers_transaction(self) -> None:
        """Preserve a caller-owned deferred read snapshot.

        Inputs: A connection already inside a read transaction.
        Outputs: A valid preview with the caller's transaction still open.
        Logic: Only commit or roll back snapshots owned by the preview itself.
        Dependencies: SQLite transaction state and preview_catalog.
        """
        connection = self.coach._db()
        connection.execute("BEGIN")
        try:
            self.assertTrue(self.coach.preview_catalog([metadata()])["import_allowed"])
            self.assertTrue(connection.in_transaction)
        finally:
            connection.rollback()

    def test_normalized_preview_hash_matches_import_receipt_and_retry(self) -> None:
        """Bind equivalent batches to the existing stable import identity.

        Inputs: Reordered problems, reversed tags, and padded titles.
        Outputs: One payload hash and one permanent applied receipt across retries.
        Logic: Normalize content without adding guard fields to operation hashing.
        Dependencies: preview_catalog, import_catalog, and receipt lookup.
        """
        first, second = metadata(), metadata(990002)
        changed = deepcopy(first)
        changed["tags"].reverse()
        changed["title"] = "  " + changed["title"] + "  "
        left = self.coach.preview_catalog([second, changed])
        right = self.coach.preview_catalog([first, second])
        self.assertEqual(left["payload_hash"], right["payload_hash"])
        receipt = self.coach.import_catalog([second, changed], "synthetic-normalized-import",
                                            expected_hash=left["payload_hash"])
        self.assertEqual(receipt["status"], "applied")
        self.assertEqual(receipt["added_count"], 2)
        self.assertEqual(receipt["payload_hash"], left["payload_hash"])
        replay = self.coach.import_catalog([first, second], "synthetic-normalized-import")
        self.assertEqual(replay, receipt)
        self.assertEqual(self.coach.receipt("synthetic-normalized-import"), receipt)
        after = self.coach.preview_catalog([first, second])
        self.assertTrue(after["import_allowed"])
        self.assertEqual(after["new_problems"], [])
        self.assertEqual(len(after["unchanged_problems"]), 2)
        self.assertEqual(after["payload_hash"], left["payload_hash"])

    def test_hash_guard_rejects_changed_content_without_a_receipt(self) -> None:
        """Refuse changed candidate files before a first write or replay.

        Inputs: One preview hash and later changed normalized metadata.
        Outputs: A hash mismatch and a completely unchanged database.
        Logic: Guard the submitted content rather than trusting a mutable path.
        Dependencies: preview_catalog, import_catalog, and SQLite dump comparison.
        """
        expected = self.coach.preview_catalog([metadata()])["payload_hash"]
        before = list(self.coach._db().iterdump())
        changed = {**metadata(), "title": "Changed synthetic candidate"}
        with self.assertRaises(CoachError) as rejected:
            self.coach.import_catalog([changed], "synthetic-changed-file", expected_hash=expected)
        self.assertEqual(rejected.exception.code, "content_hash_mismatch")
        self.assertEqual(rejected.exception.details["expected_hash"], expected)
        self.assertNotEqual(rejected.exception.details["actual_hash"], expected)
        self.assertEqual(list(self.coach._db().iterdump()), before)
        for invalid in ("", "A" * 64, "a" * 63, 12, True):
            with self.subTest(guard=invalid):
                with self.assertRaises(CoachError) as malformed:
                    self.coach.import_catalog([metadata()], "synthetic-bad-guard", expected_hash=invalid)
                self.assertEqual(malformed.exception.code, "validation_error")
        self.assertEqual(list(self.coach._db().iterdump()), before)

    def test_same_submission_with_different_content_is_rejected(self) -> None:
        """Keep prior import receipts immutable when an operation ID is reused.

        Inputs: An applied import and a second batch under the same submission ID.
        Outputs: An idempotency conflict and the original receipt and catalog.
        Logic: Compare normalized operation content before considering new entries.
        Dependencies: import_catalog and the existing replay mechanism.
        """
        receipt = self.coach.import_catalog([metadata()], "synthetic-shared-id")
        before = self.coach.list_problems()
        with self.assertRaises(CoachError) as rejected:
            self.coach.import_catalog([metadata(990002)], "synthetic-shared-id")
        self.assertEqual(rejected.exception.code, "idempotency_conflict")
        self.assertEqual(self.coach.receipt("synthetic-shared-id"), receipt)
        self.assertEqual(self.coach.list_problems(), before)

    def test_actual_import_rechecks_conflicts_after_an_allowed_preview(self) -> None:
        """Prevent a prior preview from reserving or overwriting metadata identity.

        Inputs: An allowed preview followed by an intervening conflicting import.
        Outputs: A refused later batch with neither partial rows nor a new receipt.
        Logic: Recheck all current IDs in the actual import transaction.
        Dependencies: preview_catalog, append-only imports, and immutable receipts.
        """
        candidates = [metadata(), metadata(990002)]
        preview = self.coach.preview_catalog(candidates)
        self.assertTrue(preview["import_allowed"])
        self.coach.import_catalog([{**metadata(990002), "title": "Intervening synthetic metadata"}],
                                   "synthetic-intervening-import")
        before = list(self.coach._db().iterdump())
        with self.assertRaises(CoachError) as rejected:
            self.coach.import_catalog(candidates, "synthetic-outdated-preview", preview["payload_hash"])
        self.assertEqual(rejected.exception.code, "catalog_conflict")
        self.assertEqual(list(self.coach._db().iterdump()), before)
        updated = self.coach.preview_catalog(candidates)
        self.assertFalse(updated["import_allowed"])
        self.assertEqual([row["id"] for row in updated["new_problems"]], [metadata()["id"]])
        self.assertEqual(updated["payload_hash"], preview["payload_hash"])

    def test_invalid_metadata_refuses_the_complete_batch(self) -> None:
        """Reject invalid field shapes, duplicate IDs, URLs, and label syntax.

        Inputs: Valid metadata paired with one invalid candidate.
        Outputs: Validation errors with no imported rows or receipt side effects.
        Logic: Apply the existing strict validator to preview and actual imports.
        Dependencies: catalog validation and SQLite dump comparison.
        """
        candidate = metadata(990002)
        invalid = [
            {**candidate, "statement": "Disallowed synthetic text"},
            {key: value for key, value in candidate.items() if key != "title"},
            {**candidate, "tags": ["Graph"]}, {**candidate, "tags": ["depth_first_search"]},
            {**candidate, "tags": ["array", "array"]}, {**candidate, "tags": []},
            {**candidate, "url": "https://leetcode.com.evil.test/problems/synthetic/"},
            {**candidate, "url": "http://leetcode.com/problems/synthetic/"},
            {**candidate, "url": "https://leetcode.com/problems/synthetic/?token=synthetic"},
            {**candidate, "id": "leetcode:0990002"}, {**candidate, "difficulty": "unknown"},
            metadata(),
        ]
        before = list(self.coach._db().iterdump())
        for index, problem in enumerate(invalid):
            with self.subTest(index=index):
                batch = [metadata(), problem]
                with self.assertRaises(CoachError) as preview_error:
                    self.coach.preview_catalog(batch)
                self.assertEqual(preview_error.exception.code, "validation_error")
                with self.assertRaises(CoachError) as import_error:
                    self.coach.import_catalog(batch, f"synthetic-invalid-{index}")
                self.assertEqual(import_error.exception.code, "validation_error")
                self.assertEqual(list(self.coach._db().iterdump()), before)

    def test_preview_of_missing_database_never_initializes_it(self) -> None:
        """Refuse missing storage without creating a replacement workspace.

        Inputs: A Coach bound to a nonexistent directory and valid metadata.
        Outputs: A not-initialized error with no new path or SQLite file.
        Logic: Use the normal lazy reader instead of an initialization path.
        Dependencies: Coach, pathlib, and the existing storage boundary.
        """
        missing = Path(self.temporary.name) / "missing" / "coach.sqlite3"
        other = Coach(missing)
        try:
            with self.assertRaises(CoachError) as rejected:
                other.preview_catalog([metadata()])
            self.assertEqual(rejected.exception.code, "not_initialized")
            self.assertFalse(missing.parent.exists())
        finally:
            other.close()

    def test_new_labels_are_advisory_and_remote_truth_remains_unverified(self) -> None:
        """Keep canonical label syntax distinct from model or source correctness.

        Inputs: A legal new training label and an official-shaped synthetic URL.
        Outputs: An allowed local-format preview with explicit unverified source flags.
        Logic: Surface new labels without creating a closed vocabulary or network fetch.
        Dependencies: preview_catalog and policy_capabilities.
        """
        entry = {**metadata(), "tags": ["synthetic-new-topic"]}
        preview = self.coach.preview_catalog([entry])
        self.assertTrue(preview["import_allowed"])
        self.assertEqual(preview["unknown_tags"], ["synthetic-new-topic"])
        self.assertEqual(preview["verification"], {
            "metadata_format_checked": True, "official_url_format_checked": True,
            "remote_source_checked": False, "content_correctness_checked": False,
        })
        capabilities = self.coach.policy_capabilities()["supports"]
        self.assertFalse(capabilities["remote_fetch"])
        self.assertTrue(capabilities["metadata_import_preview"])
        self.assertTrue(capabilities["metadata_import_hash_guard"])

    def test_import_preserves_frozen_plan_feedback_and_scope_until_changed(self) -> None:
        """Make new metadata eligible through existing deterministic policy rules.

        Inputs: A frozen plan with feedback, then a previewed metadata import.
        Outputs: Unchanged prior records and a later scoped selection of the new problem.
        Logic: Keep catalog expansion separate from policy activation and published plans.
        Dependencies: Coach imports, policy proposal/activation, and deterministic planning.
        """
        self.coach.ensure_plan("2026-01-01")
        original_item = self.coach.get_plan("2026-01-01")["items"][0]
        self.coach.submit_feedback(original_item["attempt_id"], "synthetic-preserved-feedback", 0,
                                   {"result": "D", "elapsed_minutes": 20},
                                   occurred_at="2026-01-01T12:00:00+00:00")
        frozen = self.coach.get_plan("2026-01-01")
        history = self.coach.history(original_item["attempt_id"])
        policy_before = self.coach.policy_history()
        candidate = metadata()
        preview = self.coach.preview_catalog([candidate])
        receipt = self.coach.import_catalog([candidate], "synthetic-scope-import", preview["payload_hash"])
        self.assertEqual(receipt["status"], "applied")
        self.assertIn(candidate, self.coach.list_problems()["problems"])
        self.assertEqual(self.coach.policy_history(), policy_before)
        self.assertEqual(self.coach.get_plan("2026-01-01"), frozen)
        replayed_plan = self.coach.ensure_plan("2026-01-01")
        self.assertFalse(replayed_plan.pop("created"))
        self.assertEqual(replayed_plan, frozen)
        self.assertEqual(self.coach.history(original_item["attempt_id"]), history)
        proposal = self.coach.propose_policy({"effective_from": "2026-01-02",
                                               "topics_any": ["array"], "difficulties": ["easy"],
                                               "problem_ids": [candidate["id"]]}, 0, "synthetic-new-scope")
        self.coach.activate_policy(proposal["proposal_id"], 0, proposal["content_hash"], "synthetic-activate-scope")
        later = self.coach.ensure_plan("2026-01-02")
        self.assertEqual([row["problem"]["id"] for row in later["items"]], [candidate["id"]])
        self.assertEqual(self.coach.history(original_item["attempt_id"]), history)


if __name__ == "__main__":
    unittest.main()
