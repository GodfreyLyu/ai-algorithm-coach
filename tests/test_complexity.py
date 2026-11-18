"""Test version-bound code reviews and durable pending work with synthetic records."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.errors import CoachError
from algorithm_coach.service import Coach


class ComplexityTests(unittest.TestCase):
    """Keep host analysis separate from reported outcomes and current code versions."""

    def setUp(self) -> None:
        """Inputs: none. Outputs: one temporary practice attempt.

        Logic: initialize synthetic data and reserve its first plan item.
        Dependencies: tempfile and Coach.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.coach = Coach(Path(self.temp.name) / "private" / "coach.sqlite3")
        self.coach.initialize()
        self.attempt = self.coach.ensure_plan("2026-01-01")["items"][0]["attempt_id"]

    def tearDown(self) -> None:
        """Inputs: fixture resources. Outputs: none.

        Logic: release SQLite before deleting temporary files.
        Dependencies: Coach and tempfile.
        """
        self.coach.close()
        self.temp.cleanup()

    def _evidence(self, submission: str = "code-one", code: str = "return 1;") -> dict:
        """Inputs: a stable ID and code. Outputs: an evidence receipt.

        Logic: bind code to the current feedback revision.
        Dependencies: Coach.record_solution and history.
        """
        revision = self.coach.history(self.attempt)["attempt"]["revision"]
        return self.coach.record_solution(self.attempt, submission, revision,
                                          {"code": code, "language": "Java", "input_definition": "n is input length"})

    def _review(self, evidence: dict, submission: str = "review-one") -> dict:
        """Inputs: evidence and a stable action ID. Outputs: a review receipt.

        Logic: record only the scoped conclusion supported by this synthetic code.
        Dependencies: Coach.submit_complexity_review.
        """
        return self.coach.submit_complexity_review(submission, {
            "evidence_id": evidence["evidence_id"], "status": "supported",
            "input_definition": "n is input length", "time_complexity": "O(1)",
            "space_complexity": "O(1)", "reasoning": "The code returns one constant.",
            "reviewer": "synthetic-host", "sources": ["submitted code"],
            "learning_evidence": {"complexity": True},
        })

    def test_review_does_not_change_ac_or_overwrite_self_report(self) -> None:
        """Inputs: a user report and scoped analysis. Outputs: separate saved evidence.

        Logic: compare feedback and revisions before and after reviewing code.
        Dependencies: immutable history and complexity status.
        """
        self.coach.submit_feedback(self.attempt, "report", 0,
                                   {"result": "D", "time_complexity": "O(n)"})
        before = self.coach.history(self.attempt)
        evidence = self._evidence()
        receipt = self._review(evidence)
        self.assertEqual(receipt, self._review(evidence))
        after = self.coach.history(self.attempt)
        self.assertEqual(before["revisions"], after["revisions"])
        self.assertEqual(after["attempt"]["feedback"]["time_complexity"], "O(n)")
        self.assertEqual(after["attempt"]["feedback"]["result"], "D")
        status = self.coach.complexity_status(self.attempt)["items"][0]
        self.assertEqual(status["status"], "supported")
        self.assertEqual(status["review"]["body"]["time_complexity"], "O(1)")

    def test_pending_survives_reopen_and_changed_feedback_stales_review(self) -> None:
        """Inputs: saved code and a later report. Outputs: pending and stale statuses.

        Logic: reopen the authority, review, then submit a new feedback revision.
        Dependencies: SQLite persistence and exact version binding.
        """
        evidence = self._evidence()
        self.coach.close()
        self.assertEqual(self.coach.complexity_status(self.attempt)["items"][0]["status"], "pending")
        self._review(evidence)
        self.coach.submit_feedback(self.attempt, "later-report", 0, {"result": "D"})
        self.assertEqual(self.coach.complexity_status(self.attempt)["items"][0]["status"], "stale")
        with self.assertRaises(CoachError) as raised:
            self._review(evidence, "stale-review")
        self.assertEqual(raised.exception.code, "revision_conflict")

    def test_new_code_rejects_old_evidence_and_retries_do_not_duplicate(self) -> None:
        """Inputs: two code versions. Outputs: one row per action and stale rejection.

        Logic: replay identical code, append changed code, and reject its older review.
        Dependencies: stable receipts and evidence identity checks.
        """
        old = self._evidence()
        self.assertEqual(old, self._evidence())
        self._evidence("code-two", "return 2;")
        with self.assertRaises(CoachError) as raised:
            self._review(old)
        self.assertEqual(raised.exception.code, "revision_conflict")
        count = self.coach._db().execute("SELECT COUNT(*) FROM solution_evidence").fetchone()[0]
        self.assertEqual(count, 2)
        self.assertEqual(self.coach.history(self.attempt)["attempt"]["revision"], 0)

    def test_research_cannot_close_work_or_change_original_identity(self) -> None:
        """Inputs: research containing outcome fields. Outputs: rejected changes.

        Logic: prevent source context from becoming an alternative completion channel.
        Dependencies: strict training context validation and immutable attempts.
        """
        problem = self.coach.history(self.attempt)["attempt"]["problem_id"]
        for key, value in (("completion_confirmed", True), ("archive_only", True),
                           ("training_identity", "new"), ("seed_feedback_revision", 100)):
            with self.assertRaises(CoachError):
                self.coach.save_training_context("bad-" + key, {
                    "problem_id": problem, "attempt_id": self.attempt, "context": {key: value},
                })
        self.assertEqual(self.coach.history(self.attempt)["attempt"]["revision"], 0)
        self.assertEqual(self.coach._db().execute("SELECT COUNT(*) FROM training_contexts").fetchone()[0], 0)

    def test_manual_profile_work_cannot_duplicate_a_problem_or_framework(self) -> None:
        """Inputs: two researched problems sharing a framework. Outputs: one allocation.

        Logic: exercise manual practice through the same daily framework gate.
        Dependencies: Coach context, config, and manual practice operations.
        """
        self.coach.update_config({"training_profile": "tokyo-interview-v1", "daily_count": 6}, 1)
        for problem in ("leetcode:1", "leetcode:242"):
            self.coach.save_training_context("context-" + problem, {
                "problem_id": problem, "context": {"primary_framework": "hash-table", "score": [30, 20, 10, 8, 4],
                    "source_verified": True, "source_verification": {"official": {"scope": "Synthetic checked metadata"}}},
            })
        self.coach.start_practice("leetcode:1", "manual-one", training_date="2026-01-02")
        for problem in ("leetcode:1", "leetcode:242"):
            with self.assertRaises(CoachError) as raised:
                self.coach.start_practice(problem, "duplicate-" + problem, training_date="2026-01-02")
            self.assertEqual(raised.exception.code, "daily_framework_conflict")


if __name__ == "__main__":
    unittest.main()
