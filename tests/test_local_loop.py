"""Verify local training behavior, feedback history, and recovery with synthetic data."""

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.errors import CoachError
from algorithm_coach.service import Coach


class LocalLoopTests(unittest.TestCase):
    """Test the shared application boundary with isolated databases."""

    def setUp(self) -> None:
        """Create an isolated local authority.

        Inputs: None.
        Outputs: A temporary directory and an initialized Coach.
        Logic: Use only synthetic configuration and a private temporary path.
        Dependencies: tempfile, pathlib, and Coach.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "private" / "coach.sqlite3"
        self.coach = Coach(self.db)
        self.coach.initialize({"timezone": "UTC", "daily_count": 5})

    def tearDown(self) -> None:
        """Release the database and remove synthetic data.

        Inputs: The fixture created by setUp.
        Outputs: None.
        Logic: Close SQLite before removing the temporary directory.
        Dependencies: Coach and tempfile.
        """
        self.coach.close()
        self.temp.cleanup()

    def _feedback(self, item: dict, result: str, submission: str,
                  revision: int = 0, kind: str = "progress", day: str = "2026-01-01",
                  **extra: object) -> dict:
        """Submit synthetic feedback to a known practice.

        Inputs: A plan item, result, operation ID, version, kind, date, and optional fields.
        Outputs: A committed receipt.
        Logic: Use an explicit occurrence time for repeatable date tests.
        Dependencies: Coach.submit_feedback.
        """
        return self.coach.submit_feedback(
            item["attempt_id"], submission, revision, {"result": result, **extra},
            kind=kind, occurred_at=f"{day}T12:00:00+00:00",
        )

    def test_plan_survives_restart_and_repeated_publication(self) -> None:
        """Keep the same plan and feedback after a restart.

        Inputs: One synthetic plan and accepted feedback.
        Outputs: Assertions about stable IDs and the saved revision.
        Logic: Close and reopen the authority, then rerun plan generation.
        Dependencies: Coach and SQLite persistence.
        """
        plan = self.coach.ensure_plan("2026-01-01")
        self.assertEqual(len(plan["items"]), 5)
        self._feedback(plan["items"][0], "A", "plan-restart")
        self.coach.close()
        self.coach = Coach(self.db)
        repeated = self.coach.ensure_plan("2026-01-01")
        self.assertFalse(repeated["created"])
        self.assertEqual(plan["id"], repeated["id"])
        self.assertEqual([item["attempt_id"] for item in plan["items"]],
                         [item["attempt_id"] for item in repeated["items"]])
        self.assertEqual(repeated["items"][0]["attempt"]["feedback"]["result"], "A")

    def test_idempotent_retry_returns_original_receipt(self) -> None:
        """Make retries safe even when the first response was lost.

        Inputs: Two identical writes with the same operation ID.
        Outputs: Equal receipts and one feedback revision.
        Logic: Replay with the original expected version after the first commit.
        Dependencies: Coach receipts and optimistic concurrency.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        first = self._feedback(item, "A", "lost-response", elapsed_minutes=25)
        second = self._feedback(item, "A", "lost-response", elapsed_minutes=25)
        self.assertEqual(first, second)
        self.assertEqual(first, self.coach.receipt("lost-response"))
        self.assertEqual(first["status"], "applied")
        self.assertEqual(len(self.coach.history(item["attempt_id"])["revisions"]), 1)

    def test_reused_operation_with_changed_payload_is_rejected(self) -> None:
        """Prevent one operation ID from referring to two facts.

        Inputs: The same operation ID with A and C.
        Outputs: A conflict and the original feedback.
        Logic: Verify payload identity before accepting a retry.
        Dependencies: Coach feedback contract.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "A", "same-id")
        with self.assertRaises(CoachError):
            self._feedback(item, "C", "same-id")
        self.assertEqual(self.coach.history(item["attempt_id"])["attempt"]["feedback"]["result"], "A")

    def test_concurrent_clients_cannot_silently_overwrite(self) -> None:
        """Reject a stale client's conflicting feedback.

        Inputs: Two connections that start with feedback revision zero.
        Outputs: A conflict from the stale write.
        Logic: Save through one connection, then submit through the other.
        Dependencies: SQLite and Coach expected_revision checks.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        other = Coach(self.db)
        try:
            self._feedback(item, "A", "client-one")
            with self.assertRaises(CoachError):
                other.submit_feedback(item["attempt_id"], "client-two", 0, {"result": "E"})
        finally:
            other.close()
        self.assertEqual(len(self.coach.history(item["attempt_id"])["revisions"]), 1)

    def test_d_continues_same_attempt_across_days(self) -> None:
        """Count a long practice once rather than once per training day.

        Inputs: D on day one and A on day three.
        Outputs: The same practice ID and two progress snapshots.
        Logic: Carry the unfinished practice into the next frozen plan.
        Dependencies: Coach planning, feedback, and history.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "D", "unfinished", elapsed_minutes=20)
        next_plan = self.coach.ensure_plan("2026-01-03")
        self.assertIn(item["attempt_id"], [row["attempt_id"] for row in next_plan["items"]])
        self._feedback(item, "A", "finished", revision=1, day="2026-01-03", elapsed_minutes=40)
        history = self.coach.history(item["attempt_id"])
        self.assertEqual(history["attempt"]["feedback"]["elapsed_minutes"], 40)
        self.assertEqual(len(history["revisions"]), 2)
        state = self.coach.learning_state()
        row = next(row for row in state["problems"] if row["problem_id"] == item["problem"]["id"])
        self.assertEqual(row["completed_count"], 1)

    def test_correction_keeps_history_and_recomputes_state(self) -> None:
        """Use corrected facts without deleting the old report.

        Inputs: A corrected to C on one practice.
        Outputs: Both revisions and no independent completion for that practice.
        Logic: Rebuild learning evidence from effective feedback snapshots.
        Dependencies: Coach feedback revisions and derived state.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "A", "initial-report")
        self._feedback(item, "C", "correct-report", revision=1, kind="correction")
        history = self.coach.history(item["attempt_id"])
        self.assertEqual([row["snapshot"]["result"] for row in history["revisions"]], ["A", "C"])
        row = next(row for row in self.coach.learning_state()["problems"]
                   if row["problem_id"] == item["problem"]["id"])
        self.assertEqual(row["independent_count"], 0)
        self.assertEqual(row["completed_count"], 1)

    def test_omitted_false_and_cleared_fields_stay_distinct(self) -> None:
        """Preserve the difference between an unanswered field and false.

        Inputs: An explicit false, an omitted field, and an explicit null.
        Outputs: The matching feedback values in history.
        Logic: Merge only explicit changes and preserve immutable snapshots.
        Dependencies: Coach partial feedback contract.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "D", "false-field", boundary_tests=False)
        self.coach.submit_feedback(item["attempt_id"], "omit-field", 1, {"elapsed_minutes": 10})
        self.assertIs(self.coach.history(item["attempt_id"])["attempt"]["feedback"]["boundary_tests"], False)
        self.coach.submit_feedback(item["attempt_id"], "clear-field", 2,
                                   {"boundary_tests": None}, kind="correction")
        self.assertIsNone(self.coach.history(item["attempt_id"])["attempt"]["feedback"]["boundary_tests"])

    def test_no_response_is_not_d_or_completion(self) -> None:
        """Keep scheduled but unanswered practices unknown.

        Inputs: A plan with no feedback.
        Outputs: Unknown feedback and zero completions.
        Logic: Query the stored plan and derived learning state.
        Dependencies: Coach plans and projections.
        """
        plan = self.coach.ensure_plan("2026-01-01")
        self.assertTrue(all(item["attempt"]["feedback"] is None for item in plan["items"]))
        self.assertTrue(all(row["completed_count"] == 0 for row in self.coach.learning_state()["problems"]))

    def test_defer_and_skip_do_not_complete_or_imply_weakness(self) -> None:
        """Respect explicit defer and skip decisions.

        Inputs: E with a future date and F on two scheduled practices.
        Outputs: Neither practice appears in tomorrow's plan or completion counts.
        Logic: Apply scheduling decisions without inferring failed ability.
        Dependencies: Coach and deterministic selection.
        """
        plan = self.coach.ensure_plan("2026-01-01")
        first, second = plan["items"][:2]
        self._feedback(first, "E", "deferred", defer_until="2026-01-05")
        self._feedback(second, "F", "skipped")
        tomorrow = self.coach.ensure_plan("2026-01-02")
        attempt_ids = [item["attempt_id"] for item in tomorrow["items"]]
        self.assertNotIn(first["attempt_id"], attempt_ids)
        self.assertNotIn(second["attempt_id"], attempt_ids)
        for row in self.coach.learning_state()["problems"]:
            self.assertEqual(row["completed_count"], 0)

    def test_full_backlog_uses_all_slots_without_extra_new_problems(self) -> None:
        """Treat the daily count as total capacity.

        Inputs: Five unanswered practices.
        Outputs: The same five practices tomorrow.
        Logic: Prioritize continuation before allocating new work.
        Dependencies: Coach selection rules.
        """
        today = self.coach.ensure_plan("2026-01-01")
        tomorrow = self.coach.ensure_plan("2026-01-02")
        self.assertEqual({row["attempt_id"] for row in today["items"]},
                         {row["attempt_id"] for row in tomorrow["items"]})
        self.assertEqual(len(tomorrow["items"]), 5)

    def test_invalid_feedback_does_not_advance_revision(self) -> None:
        """Reject malformed or forged feedback before saving it.

        Inputs: Invalid results, numeric types, fields, and claimed verification.
        Outputs: Validation failures and an untouched practice.
        Logic: Try each invalid payload against the same revision.
        Dependencies: Coach validation and history.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        invalid = [{"result": "Z"}, {"elapsed_minutes": -1}, {"elapsed_minutes": True},
                   {"proficiency": True}, {"boundary_tests": "yes"},
                   {"verified": True}, {"verified_complexity": "O(n)"},
                   {"elapsed_minutes": float("nan")}, {"defer_until": "tomorrow"}]
        for index, changes in enumerate(invalid):
            with self.subTest(changes=changes):
                with self.assertRaises(CoachError):
                    self.coach.submit_feedback(item["attempt_id"], f"invalid-{index}", 0, changes)
        self.assertEqual(self.coach.history(item["attempt_id"])["attempt"]["revision"], 0)

    def test_hint_dependence_cannot_be_erased_by_progress(self) -> None:
        """Prevent continued work from masquerading as a fresh independent solution.

        Inputs: D after a hint, followed by a progress report of A.
        Outputs: Rejection of the inconsistent progress claim.
        Logic: Preserve assistance within an attempt unless a fact is corrected.
        Dependencies: Coach feedback merge rules.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "D", "used-hint", assistance="hint")
        with self.assertRaises(CoachError):
            self._feedback(item, "A", "claim-independent", revision=1)

    def test_backup_restores_history_and_rebuildable_state(self) -> None:
        """Recover a complete local loop from a consistent snapshot.

        Inputs: Feedback and a backup file.
        Outputs: Equal restored history and semantic state.
        Logic: Open the backup as an authority and rebuild its projections.
        Dependencies: SQLite backup API and Coach rebuild.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "B", "backup-report", elapsed_minutes=30)
        backup = Path(self.temp.name) / "snapshot.sqlite3"
        self.coach.backup(backup)
        recovered = Coach(backup)
        try:
            self.assertEqual(recovered.history(item["attempt_id"]), self.coach.history(item["attempt_id"]))
            before = recovered.learning_state()
            recovered.rebuild_state()
            after = recovered.learning_state()
            for key in ("problems", "topics"):
                self.assertEqual(before[key], after[key])
            self.assertEqual(recovered.ensure_plan("2026-01-02")["items"][0]["attempt_id"],
                             self.coach.ensure_plan("2026-01-02")["items"][0]["attempt_id"])
        finally:
            recovered.close()
        with self.assertRaises((CoachError, FileExistsError)):
            self.coach.backup(backup)

    def test_invalid_config_is_not_saved(self) -> None:
        """Keep invalid timezone or capacity changes out of the authority.

        Inputs: Invalid configuration patches.
        Outputs: Validation failures and the original configuration.
        Logic: Validate before updating the config revision.
        Dependencies: Coach configuration version checks.
        """
        initial = self.coach.get_config()
        for changes in ({"timezone": "Invalid/Zone"}, {"daily_count": 0}, {"daily_count": True}):
            with self.assertRaises(CoachError):
                self.coach.update_config(changes, initial["revision"])
        self.assertEqual(initial, self.coach.get_config())

    def test_checks_foreign_keys_and_integrity(self) -> None:
        """Verify the database can be inspected without changing user feedback.

        Inputs: A valid synthetic database.
        Outputs: A successful check and unchanged history.
        Logic: Run the public integrity operation after saving feedback.
        Dependencies: SQLite and Coach integrity checks.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "D", "integrity-report")
        before = self.coach.history(item["attempt_id"])
        self.coach.integrity_check()
        self.assertEqual(before, self.coach.history(item["attempt_id"]))

    def test_failed_receipt_write_rolls_back_feedback_and_learning_state(self) -> None:
        """Leave no partial feedback if the final transaction write fails.

        Inputs: A database trigger that fails before saving a submission receipt.
        Outputs: No revision, no receipt, and the original learning state.
        Logic: Fail after feedback and state writes, then inspect public results.
        Dependencies: SQLite triggers and the Coach transaction boundary.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        before = self.coach.learning_state()
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON submissions "
                               "BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
            connection.commit()
            with self.assertRaises(CoachError):
                self._feedback(item, "C", "failed-final-write")
            self.assertEqual(self.coach.history(item["attempt_id"])["revisions"], [])
            self.assertEqual(self.coach.learning_state(), before)
            with self.assertRaises(CoachError):
                self.coach.receipt("failed-final-write")
            connection.execute("DROP TRIGGER fail_receipt")
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(self._feedback(item, "C", "failed-final-write")["revision"], 1)

    def test_started_unfinished_work_precedes_unanswered_slots(self) -> None:
        """Resume real unfinished work before untouched scheduled work.

        Inputs: One D among four unanswered practices from the same day.
        Outputs: The D attempt is first tomorrow.
        Logic: Rank known continuation without treating missing feedback as D.
        Dependencies: Coach and deterministic continuation priority.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][-1]
        self._feedback(item, "D", "worked-on-it", elapsed_minutes=20)
        self.assertEqual(self.coach.ensure_plan("2026-01-02")["items"][0]["attempt_id"], item["attempt_id"])

    def test_assistance_can_increase_as_unfinished_work_progresses(self) -> None:
        """Infer newly used assistance from a later B or C report.

        Inputs: D without help, followed by B, then a corrected D and C.
        Outputs: Hint and solution dependence in the matching snapshots.
        Logic: Allow increasing help while rejecting false independent claims.
        Dependencies: Coach feedback merge rules.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "D", "no-help-yet", assistance="none")
        self._feedback(item, "B", "hint-finished", revision=1)
        self.assertEqual(self.coach.history(item["attempt_id"])["attempt"]["feedback"]["assistance"], "hint")
        self._feedback(item, "D", "not-finished-actually", revision=2, kind="correction")
        self._feedback(item, "C", "answer-finished", revision=3)
        self.assertEqual(self.coach.history(item["attempt_id"])["attempt"]["feedback"]["assistance"], "solution")

    def test_stable_mastery_needs_spaced_separate_practices(self) -> None:
        """Require independent practice dates rather than repeated feedback edits.

        Inputs: Separate A practices on days zero, three, and ten.
        Outputs: Stable self-reported evidence after the third practice.
        Logic: Create explicit redos and submit one result for each attempt.
        Dependencies: Coach practice creation and review rules.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "A", "first-independent")
        for index, day in enumerate(("2026-01-04", "2026-01-11"), start=1):
            created = self.coach.start_practice(item["problem"]["id"], f"redo-{index}", training_date=day)
            self._feedback({"attempt_id": created["attempt_id"]}, "A", f"independent-{index}", day=day)
        state = self.coach.learning_state()
        row = next(row for row in state["problems"] if row["problem_id"] == item["problem"]["id"])
        self.assertEqual(row["mastery_status"], "stable")
        self.assertEqual(row["independent_count"], 3)
        self.assertEqual(state["basis"], "self_reported")
        self._feedback(item, "C", "correct-first-independent", revision=1, kind="correction")
        row = next(row for row in self.coach.learning_state()["problems"]
                   if row["problem_id"] == item["problem"]["id"])
        self.assertNotEqual(row["mastery_status"], "stable")

    def test_same_day_independent_redos_do_not_prove_stable_mastery(self) -> None:
        """Keep many same-day attempts from satisfying spacing rules.

        Inputs: Three A attempts on the same date.
        Outputs: Three reports but no stable mastery.
        Logic: Count practice occurrences and spacing as separate concepts.
        Dependencies: Coach and mastery rules.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "A", "same-day-initial")
        for index in range(2):
            created = self.coach.start_practice(item["problem"]["id"], f"same-day-redo-{index}",
                                                training_date="2026-01-01")
            self._feedback({"attempt_id": created["attempt_id"]}, "A", f"same-day-a-{index}")
        row = next(row for row in self.coach.learning_state()["problems"]
                   if row["problem_id"] == item["problem"]["id"])
        self.assertEqual(row["independent_count"], 3)
        self.assertNotEqual(row["mastery_status"], "stable")

    def test_due_defer_resumes_original_attempt(self) -> None:
        """Resume a deferred practice only when its chosen date arrives.

        Inputs: A deferred practice with a future date.
        Outputs: The same attempt is selected on that date.
        Logic: Keep deferral separate from completion and redo creation.
        Dependencies: Coach and resume date filtering.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "E", "resume-date", defer_until="2026-01-05")
        ids = [row["attempt_id"] for row in self.coach.ensure_plan("2026-01-05")["items"]]
        self.assertIn(item["attempt_id"], ids)

    def test_skipped_retest_is_never_reopened_as_same_attempt(self) -> None:
        """Preserve a skipped retest while allowing a later fresh practice.

        Inputs: B, a due retest, and F on that retest.
        Outputs: A new retest ID after cooldown, with the F history retained.
        Logic: Never revive a closed attempt when its source review is due again.
        Dependencies: Coach review reconciliation and cooldown rules.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "B", "assisted-source")
        next_plan = self.coach.ensure_plan("2026-01-02")
        retest = next(row for row in next_plan["items"] if row["problem"]["id"] == item["problem"]["id"])
        self._feedback(retest, "F", "skip-retest", day="2026-01-02")
        later = self.coach.ensure_plan("2026-01-10")
        replacement = next(row for row in later["items"] if row["problem"]["id"] == item["problem"]["id"])
        self.assertNotEqual(retest["attempt_id"], replacement["attempt_id"])
        self.assertEqual(self.coach.history(retest["attempt_id"])["attempt"]["feedback"]["result"], "F")

    def test_correction_without_event_time_preserves_practice_date(self) -> None:
        """Keep a late correction from making an old performance appear recent.

        Inputs: Feedback with an old occurrence date and a correction made now.
        Outputs: The old practice date in the effective snapshot.
        Logic: Separate event time from the time the correction is received.
        Dependencies: Coach timestamp policy.
        """
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self._feedback(item, "A", "old-report")
        self.coach.submit_feedback(item["attempt_id"], "late-correction", 1, {"result": "C"},
                                   kind="correction")
        history = self.coach.history(item["attempt_id"])
        self.assertEqual(history["attempt"]["practice_date"], "2026-01-01")
        self.assertEqual(history["revisions"][0]["occurred_at"], history["revisions"][1]["occurred_at"])


if __name__ == "__main__":
    unittest.main()
