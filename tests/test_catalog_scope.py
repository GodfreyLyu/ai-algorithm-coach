"""Test metadata import safety and final policy checks at scheduling boundaries."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.errors import CoachError
from algorithm_coach.service import Coach


def metadata() -> dict:
    """Return a metadata-only example outside the bundled catalog.

    Inputs: None.
    Outputs: An independent public problem metadata object.
    Logic: Include a reference and training labels without copying a statement.
    Dependencies: None.
    """
    return {"id": "leetcode:27", "title": "Remove Element", "difficulty": "easy",
            "tags": ["array", "two-pointers"],
            "url": "https://leetcode.com/problems/remove-element/"}


class CatalogTests(unittest.TestCase):
    """Use synthetic local stores to inspect catalog and policy behavior."""

    def setUp(self) -> None:
        """Create an isolated authority.

        Inputs: None.
        Outputs: A private initialized Coach.
        Logic: Keep metadata imports and feedback outside the project tree.
        Dependencies: tempfile and Coach.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.coach = Coach(Path(self.temp.name) / "private" / "coach.sqlite3")
        self.coach.initialize({"timezone": "UTC"})

    def tearDown(self) -> None:
        """Remove all test state.

        Inputs: The fixture.
        Outputs: None.
        Logic: Close SQLite before discarding temporary data.
        Dependencies: Coach and tempfile.
        """
        self.coach.close()
        self.temp.cleanup()

    def test_import_is_append_only_and_idempotent(self) -> None:
        """Make imported metadata reusable without overwriting existing entries.

        Inputs: A valid new entry, a replay, and a changed title for the same ID.
        Outputs: One added entry, a stable receipt, and a conflict on overwrite.
        Logic: Compare imported content before changing catalog identity.
        Dependencies: Coach catalog import and permanent receipts.
        """
        before = self.coach.list_problems()
        receipt = self.coach.import_catalog([metadata()], "metadata-once")
        self.assertEqual(receipt, self.coach.import_catalog([metadata()], "metadata-once"))
        after = self.coach.list_problems()
        self.assertEqual(len(after["problems"]), len(before["problems"]) + 1)
        self.assertNotEqual(after["catalog_version"], before["catalog_version"])
        no_change = self.coach.import_catalog([metadata()], "metadata-identical")
        self.assertEqual(no_change["added_count"], 0)
        self.assertEqual(self.coach.list_problems()["catalog_version"], after["catalog_version"])
        with self.assertRaises(CoachError):
            self.coach.import_catalog([{**metadata(), "title": "Changed title"}], "metadata-overwrite")
        self.assertEqual(after, self.coach.list_problems())

    def test_builtin_metadata_can_be_reimported_without_order_conflicts(self) -> None:
        """Compare metadata by normalized meaning rather than tag order.

        Inputs: A bundled entry with multiple tags.
        Outputs: A no-op import and unchanged catalog version.
        Logic: Normalize both existing and incoming metadata before comparing.
        Dependencies: Coach catalog import and metadata normalization.
        """
        before = self.coach.list_problems()
        entry = next(entry for entry in before["problems"] if len(entry["tags"]) > 1)
        entry = deepcopy(entry)
        entry["tags"].reverse()
        result = self.coach.import_catalog([entry], "builtin-noop")
        self.assertEqual(result["added_count"], 0)
        self.assertEqual(self.coach.list_problems()["catalog_version"], before["catalog_version"])

    def test_unsafe_links_and_statement_fields_are_rejected_atomically(self) -> None:
        """Accept only bounded metadata and canonical official problem links.

        Inputs: Unsafe URLs, invalid labels, duplicate entries, and copied-content fields.
        Outputs: Validation errors and an unchanged catalog.
        Logic: Validate the entire batch before inserting any part of it.
        Dependencies: Coach and metadata validation.
        """
        before = self.coach.list_problems()
        invalid = [
            {**metadata(), "url": "http://leetcode.com/problems/remove-element/"},
            {**metadata(), "url": "https://leetcode.com.evil.test/problems/remove-element/"},
            {**metadata(), "url": "https://secret@leetcode.com/problems/remove-element/"},
            {**metadata(), "url": "https://leetcode.com/problems/remove-element/?token=secret"},
            {**metadata(), "url": "https://leetcode.com/problems/remove-element/#solution"},
            {**metadata(), "statement": "Synthetic disallowed content field"},
            {**metadata(), "difficulty": "extreme"},
            {**metadata(), "tags": []}, {**metadata(), "id": "leetcode:027"},
        ]
        for index, entry in enumerate(invalid):
            with self.subTest(index=index):
                entry = deepcopy(entry)
                if entry["id"] == metadata()["id"]:
                    entry["id"] = "leetcode:28"
                with self.assertRaises(CoachError):
                    self.coach.import_catalog([metadata(), entry], f"invalid-batch-{index}")
                self.assertEqual(before, self.coach.list_problems())

    def test_imported_problem_can_be_selected_and_contribute_learning_tags(self) -> None:
        """Use stored imported metadata throughout planning and learning state.

        Inputs: One imported problem and a policy limited to that problem.
        Outputs: A selected practice and nonzero evidence for its imported tag.
        Logic: Avoid depending on the original in-code catalog during projection.
        Dependencies: Coach imports, policy activation, and stored-catalog derivation.
        """
        entry = {**metadata(), "tags": ["synthetic-training-tag"]}
        self.coach.import_catalog([entry], "import-new-topic")
        proposal = self.coach.propose_policy(
            {"effective_from": "2026-01-02", "problem_ids": [entry["id"]]}, 0, "scope-imported")
        self.coach.activate_policy(proposal["proposal_id"], 0, proposal["content_hash"], "activate-imported")
        item = self.coach.ensure_plan("2026-01-02")["items"][0]
        self.assertEqual(item["problem"]["id"], entry["id"])
        self.coach.submit_feedback(item["attempt_id"], "imported-feedback", 0, {"result": "D"},
                                   occurred_at="2026-01-02T12:00:00+00:00")
        topic = next(row for row in self.coach.learning_state()["topics"]
                     if row["tag"] == "synthetic-training-tag")
        self.assertGreater(topic["weakness_score"], 0)

    def test_final_check_rejects_a_broken_selector_without_partial_writes(self) -> None:
        """Keep the publication boundary safe even if ranking returns an invalid item.

        Inputs: An active tree scope and a selector result containing an array problem.
        Outputs: A policy failure and no stored plan or reserved practice.
        Logic: Inject an invalid candidate and inspect the public saved result.
        Dependencies: Coach final validation, transaction rollback, and unittest.mock.
        """
        proposal = self.coach.propose_policy(
            {"effective_from": "2026-01-02", "topics_any": ["tree"]}, 0, "strict-tree")
        self.coach.activate_policy(proposal["proposal_id"], 0, proposal["content_hash"], "activate-tree")
        invalid = [{"problem_id": "leetcode:1", "attempt_id": None,
                    "reason": "foundation", "review_source_attempt_id": None}]
        with patch("algorithm_coach.store.policy_store.select_candidates", return_value=invalid):
            with self.assertRaises(CoachError):
                self.coach.ensure_plan("2026-01-02")
        with self.assertRaises(CoachError):
            self.coach.get_plan("2026-01-02")
        self.assertEqual(self.coach.learning_state()["attempts"], [])


if __name__ == "__main__":
    unittest.main()
