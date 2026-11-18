"""Test confirmed native checkpoints with synthetic current-schema outcomes."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.rules import derive_learning_state, default_config
from algorithm_coach.errors import CoachError
from algorithm_coach.service import Coach
from algorithm_coach import storage
from algorithm_coach.training_profile import assessment_version, learning_outcome
from test_training_profile import _attempt, _catalog, _checkpoint, _config


class LearningCheckpointTests(unittest.TestCase):
    """Preserve confirmed decisions while new evidence changes the right scope."""

    def test_unchanged_checkpoint_retains_all_confirmed_business_fields(self) -> None:
        """Inputs: a confirmed boundary. Outputs: identical business state.

        Logic: Keep a known date and count that a partial evidence replay cannot infer.
        Dependencies: Native checkpoints and the pure learning projection.
        """
        item = _attempt("one", "2026-01-01")
        checkpoint = _checkpoint([item], completed_count=12, independent_count=10,
                                 review_count=7, review_due="2026-01-31")
        item["learning_checkpoint"] = checkpoint
        state = derive_learning_state([item], _config(), _catalog())["problems"][0]
        for field, value in checkpoint["state"].items():
            if field != "evidence_coverage":
                self.assertEqual(state[field], value)
        self.assertEqual(state["evidence_coverage"], "partial")

    def test_checkpoint_from_another_rule_version_is_rejected(self) -> None:
        """Inputs: a checkpoint from another rule. Outputs: an explicit mismatch.

        Logic: Do not silently reuse confirmed state under different learning rules.
        Dependencies: The profile's checkpoint boundary and CoachError.
        """
        item = _attempt("one", "2026-01-01")
        checkpoint = _checkpoint([item])
        checkpoint["rule_version"] = "other-interview-rule"
        item["learning_checkpoint"] = checkpoint
        with self.assertRaises(CoachError) as raised:
            derive_learning_state([item], _config(), _catalog())
        self.assertEqual(raised.exception.code, "checkpoint_rule_mismatch")

    def test_standard_profile_replays_only_complete_checkpoint_evidence(self) -> None:
        """Inputs: complete or partial checkpoints. Outputs: replay or explicit refusal.

        Logic: Do not discard confirmed partial state while applying another profile.
        Dependencies: Standard rules and checkpoint coverage.
        """
        item = _attempt("one", "2026-01-01")
        checkpoint = _checkpoint([item])
        item["learning_checkpoint"] = checkpoint
        with self.assertRaises(CoachError) as raised:
            derive_learning_state([item], default_config(), _catalog())
        self.assertEqual(raised.exception.code, "checkpoint_profile_unsupported")
        checkpoint["evidence_coverage"] = "complete"
        state = derive_learning_state([item], default_config(), _catalog())["problems"][0]
        self.assertEqual(state["completed_count"], 1)
        self.assertEqual(state["independent_count"], 1)

    def test_partial_checkpoint_profile_switch_rolls_back_config_and_state(self) -> None:
        """Inputs: a current store with partial confirmed state. Outputs: no changes.

        Logic: Reject an incompatible profile inside the normal config transaction.
        Dependencies: Coach, current schema, and an isolated synthetic database.
        """
        with tempfile.TemporaryDirectory() as temporary:
            coach = Coach(Path(temporary) / "private" / "coach.sqlite3")
            try:
                coach.initialize()
                attempt_id = coach.ensure_plan("2026-01-01")["items"][0]["attempt_id"]
                coach.submit_feedback(attempt_id, "synthetic-complete", 0,
                                      {"result": "A", "elapsed_minutes": 5})
                coach.update_config({"training_profile": "tokyo-interview-v1"}, 1)
                records = [item for item in coach._attempts() if item["id"] == attempt_id]
                problem_id = records[0]["problem_id"]
                state = next(item for item in coach._state()["problems"] if item["problem_id"] == problem_id)
                checkpoint = {"state": state, "rule_version": "tokyo-interview-v1", "evidence_coverage": "partial",
                              "feedback_revisions": {item["id"]: item["revision"] for item in records},
                              "assessment_versions": {item["id"]: assessment_version(item) for item in records},
                              "outcomes": {item["id"]: learning_outcome(item) for item in records}}
                with storage.transaction(coach._db()):
                    coach._db().execute("INSERT INTO learning_checkpoints VALUES (?, ?, ?, ?)",
                                        (problem_id, "Java", storage.canonical_json(checkpoint), "2026-01-01T00:00:00+00:00"))
                before = deepcopy(coach._state())
                with self.assertRaises(CoachError) as raised:
                    coach.update_config({"training_profile": "standard"}, 2)
                self.assertEqual(raised.exception.code, "checkpoint_profile_unsupported")
                self.assertEqual(coach.get_config()["revision"], 2)
                self.assertEqual(coach.get_config()["config"]["training_profile"], "tokyo-interview-v1")
                self.assertEqual(coach._state(), before)
            finally:
                coach.close()

    def test_new_dated_success_continues_counts_and_stable_evidence(self) -> None:
        """Inputs: a boundary and a later independent review. Outputs: one new success.

        Logic: Apply one dated attempt without replaying or discarding confirmed totals.
        Dependencies: Checkpoint outcomes and the interview review rule.
        """
        old = _attempt("old", "2026-01-01")
        checkpoint = _checkpoint([old], completed_count=12, independent_count=10, review_count=7)
        old["learning_checkpoint"] = checkpoint
        later = _attempt("later", "2026-01-08")
        state = derive_learning_state([old, later], _config(), _catalog())["problems"][0]
        self.assertEqual(state["completed_count"], 13)
        self.assertEqual(state["independent_count"], 11)
        self.assertEqual(state["review_count"], 8)
        self.assertEqual(state["consecutive_stable_passes"], 2)
        self.assertTrue(state["transfer_eligible"])
        self.assertEqual(state["review_interval_range"], [14, 30])

    def test_changed_current_code_revokes_its_prior_scoped_proof(self) -> None:
        """Inputs: new code on the same report. Outputs: no retained stable proof.

        Logic: Version changes matter even without a new feedback revision.
        Dependencies: The assessment identity and explicit unknown proof values.
        """
        item = _attempt("one", "2026-01-01")
        item["assessment_version"] = "reviewed-code-one"
        checkpoint = _checkpoint([item], consecutive_stable_passes=2, transfer_eligible=True)
        item["learning_checkpoint"] = checkpoint
        item["assessment_version"] = "pending-code-two"
        item["assessment"] = {}
        state = derive_learning_state([item], _config(), _catalog())["problems"][0]
        self.assertEqual(state["consecutive_stable_passes"], 0)
        self.assertFalse(state["transfer_eligible"])
        self.assertEqual(state["independent_count"], checkpoint["state"]["independent_count"])
        self.assertEqual(state["review_interval_range"], [7, 14])

    def test_equivalent_review_identity_refresh_preserves_confirmed_streak(self) -> None:
        """Inputs: equivalent full proof with a new review ID. Outputs: the same state.

        Logic: A transport or review identity change is not another practice result.
        Dependencies: Semantic learning outcomes and the confirmed checkpoint.
        """
        item = _attempt("one", "2026-01-08")
        item["assessment_version"] = "review-one"
        checkpoint = _checkpoint([item], consecutive_stable_passes=2,
                                 transfer_eligible=True, mastery_status="stable", review_count=7)
        item["learning_checkpoint"] = checkpoint
        item["assessment_version"] = "review-two"
        state = derive_learning_state([item], _config(), _catalog())["problems"][0]
        self.assertEqual(state["consecutive_stable_passes"], 2)
        self.assertTrue(state["transfer_eligible"])
        self.assertEqual(state["review_count"], 7)
        self.assertEqual(state["review_due"], checkpoint["state"]["review_due"])

    def test_detail_only_feedback_revision_keeps_the_same_learning_decision(self) -> None:
        """Inputs: a corrected note with unchanged performance. Outputs: stable decisions.

        Logic: Preserve earlier qualifying evidence when only prose is clarified.
        Dependencies: Feedback revisions and semantic checkpoint comparison.
        """
        item = _attempt("one", "2026-01-08")
        checkpoint = _checkpoint([item], consecutive_stable_passes=2,
                                 transfer_eligible=True, mastery_status="stable")
        item["learning_checkpoint"] = checkpoint
        item["revision"] += 1
        item["feedback"]["blocked_on"] = "Corrected a spelling error in my note."
        state = derive_learning_state([item], _config(), _catalog())["problems"][0]
        self.assertEqual(state["consecutive_stable_passes"], 2)
        self.assertEqual(state["completed_count"], checkpoint["state"]["completed_count"])

    def test_complete_checkpoint_allows_a_full_correction_replay(self) -> None:
        """Inputs: complete evidence and an earlier correction. Outputs: a full replay.

        Logic: Reserve unresolved reconciliation for evidence that is actually partial.
        Dependencies: Current effective feedback and the complete-coverage contract.
        """
        old = _attempt("old", "2026-01-01")
        latest = _attempt("latest", "2026-01-08")
        checkpoint = _checkpoint([old, latest])
        checkpoint["evidence_coverage"] = "complete"
        latest["learning_checkpoint"] = checkpoint
        old["revision"] = 2
        old["feedback"].update(result="C", assistance="solution")
        state = derive_learning_state([old, latest], _config(), _catalog())["problems"][0]
        self.assertFalse(state["reconciliation_required"])
        self.assertEqual(state["consecutive_stable_passes"], 1)
        self.assertEqual(state["last_practice_date"], "2026-01-08")
        self.assertEqual(state["review_source_attempt_id"], "latest")

    def test_same_day_assisted_rewrite_after_checkpoint_is_not_another_review(self) -> None:
        """Inputs: a saved assisted outcome and its same-day rewrite. Outputs: no pass.

        Logic: A new attempt identity cannot create a spaced independent result.
        Dependencies: Date de-duplication and recorded assistance.
        """
        assisted = _attempt("a-assisted", "2026-01-01", "C")
        assisted["learning_checkpoint"] = _checkpoint([assisted], review_count=7)
        rewrite = _attempt("b-rewrite", "2026-01-01")
        before = deepcopy(assisted["learning_checkpoint"])
        state = derive_learning_state([assisted, rewrite], _config(), _catalog())["problems"][0]
        self.assertEqual(state["review_count"], 7)
        self.assertEqual(state["consecutive_stable_passes"], 0)
        self.assertEqual(state["review_interval_range"], [1, 3])
        self.assertEqual(assisted["learning_checkpoint"], before)


if __name__ == "__main__":
    unittest.main()
