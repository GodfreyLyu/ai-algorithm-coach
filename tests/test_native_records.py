"""Test native history, language-specific checkpoints, and code-version projections."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.errors import CoachError
from algorithm_coach.service import Coach
from algorithm_coach.store import storage


class NativeRecordTests(unittest.TestCase):
    """Keep current-schema evidence distinct from practice allocations and outcomes."""

    def setUp(self) -> None:
        """Inputs: none. Outputs: one isolated current authority and its first attempt.

        Logic: create ordinary saved records through the standard profile.
        Dependencies: tempfile, Coach.initialize, and Coach.ensure_plan.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "private" / "coach.sqlite3"
        self.coach = Coach(self.path)
        self.coach.initialize()
        item = self.coach.ensure_plan("2026-01-01")["items"][0]
        self.attempt_id = item["attempt_id"]
        self.problem_id = item["problem"]["id"]

    def tearDown(self) -> None:
        """Inputs: fixture resources. Outputs: none.

        Logic: close the authority before deleting temporary storage.
        Dependencies: Coach.close and tempfile cleanup.
        """
        self.coach.close()
        self.temp.cleanup()

    def _note(self, identity: str, text: str, attempt_id: str | None = None, kind: str = "practice_note") -> dict:
        """Inputs: note identity, text, optional target, and evidence kind.
        Outputs: the saved synthetic note body.

        Logic: retain a note without inventing an unknown practice occurrence time.
        Dependencies: the native immutable history evidence table.
        """
        body = {"note": text}
        self.coach._db().execute("INSERT INTO history_evidence VALUES (?, ?, ?, NULL, ?, ?)",
                                 (identity, self.problem_id, attempt_id, kind, storage.canonical_json(body)))
        return body

    def _checkpoint(self, language: str = "Java") -> dict:
        """Inputs: a recorded language. Outputs: a native checkpoint body.

        Logic: bind known historical state to one problem and language only.
        Dependencies: the current checkpoint schema and canonical JSON.
        """
        body = {"state": {"problem_id": self.problem_id, "language": language,
                          "review_due": "2026-01-12", "consecutive_stable_passes": 2},
                "evidence_coverage": "partial", "feedback_revisions": {},
                "assessment_versions": {}, "outcomes": {}, "stable_dates": []}
        self.coach._db().execute("INSERT INTO learning_checkpoints VALUES (?, ?, ?, ?)",
                                 (self.problem_id, language, storage.canonical_json(body),
                                  "2026-01-02T00:00:00+00:00"))
        return body

    def test_problem_history_retains_feedback_bound_notes_and_unbound_evidence(self) -> None:
        """Inputs: one practice result, two notes, and one confirmed checkpoint.
        Outputs: complete native history with explicit note-to-attempt relationships.

        Logic: return both source scopes while retaining the actual feedback revision.
        Dependencies: history, history_for_problem, and native evidence queries.
        """
        self.coach.submit_feedback(self.attempt_id, "reported-result", 0,
                                   {"result": "D", "elapsed_minutes": 12})
        bound = self._note("bound-note", "The user described a specific stopping point.", self.attempt_id)
        unbound = self._note("unbound-note", "A dated practice round is not known.")
        checkpoint = self._checkpoint()
        history = self.coach.history_for_problem(self.problem_id)
        self.assertEqual(history["problem_id"], self.problem_id)
        self.assertEqual(len(history["attempts"]), 1)
        attempt = history["attempts"][0]
        self.assertEqual(attempt["attempt"]["id"], self.attempt_id)
        self.assertEqual(attempt["revisions"][0]["snapshot"]["result"], "D")
        self.assertEqual([(row["id"], row["body"]) for row in attempt["evidence"]], [("bound-note", bound)])
        self.assertEqual({row["id"]: row["body"] for row in history["evidence"]},
                         {"bound-note": bound, "unbound-note": unbound})
        self.assertEqual(history["checkpoints"], [{"language": "Java", "body": checkpoint}])
        self.assertEqual(self.coach.history(self.attempt_id)["evidence"], attempt["evidence"])

    def test_unbound_note_does_not_allocate_or_complete_practice(self) -> None:
        """Inputs: an unbound historical note. Outputs: queryable evidence only.

        Logic: compare persisted practice and derived state before and after saving it.
        Dependencies: the native note table, current state, and saved attempts.
        """
        before = self.coach.learning_state()
        counts = {table: self.coach._db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("attempts", "feedback", "plans", "plan_items", "reviews")}
        self._note("unknown-round", "The source gives no reliable round identity.")
        self.assertEqual(self.coach.learning_state(), before)
        after = {table: self.coach._db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                 for table in counts}
        self.assertEqual(after, counts)
        evidence = self.coach.history_for_problem(self.problem_id)["evidence"]
        self.assertEqual(evidence[0]["id"], "unknown-round")
        self.assertIsNone(evidence[0]["attempt_id"])
        self.assertIsNone(evidence[0]["occurred_at"])

    def test_checkpoint_language_cannot_leak_to_another_language_attempt(self) -> None:
        """Inputs: Java history and a later Python attempt for the same problem.
        Outputs: a checkpoint bound solely to the matching language.

        Logic: inspect both native projections after the other language is allocated.
        Dependencies: standard manual practice and the composite checkpoint identity.
        """
        checkpoint = self._checkpoint()
        python = self.coach.start_practice(self.problem_id, "python-practice", language="Python",
                                          training_date="2026-01-03")["attempt_id"]
        attempts = {item["id"]: item for item in self.coach._attempts()}
        self.assertEqual(attempts[self.attempt_id]["learning_checkpoint"], checkpoint)
        self.assertNotIn("learning_checkpoint", attempts[python])
        python_checkpoint = self._checkpoint("Python")
        attempts = {item["id"]: item for item in self.coach._attempts()}
        self.assertEqual(attempts[python]["learning_checkpoint"], python_checkpoint)
        self.assertEqual(attempts[self.attempt_id]["learning_checkpoint"], checkpoint)

    def test_native_context_and_evidence_survive_reopening_without_old_tables(self) -> None:
        """Inputs: saved native context, checkpoint, and history evidence.
        Outputs: identical records after closing and reopening the current authority.

        Logic: exercise the ordinary current-store path with no extra format tables.
        Dependencies: current native readers and persistent SQLite storage.
        """
        context = {"training_identity": "retest", "original_recommendation_date": "2026-01-01",
                   "primary_framework": "hash-table"}
        self.coach._db().execute("INSERT INTO training_contexts(problem_id, attempt_id, body, created_at) VALUES (?, ?, ?, ?)",
                                 (self.problem_id, self.attempt_id, storage.canonical_json(context),
                                  "2026-01-01T00:00:00+00:00"))
        self._checkpoint()
        self._note("saved-note", "A source note remains available after reopening.")
        before = self.coach.history_for_problem(self.problem_id)
        self.coach.close()
        self.coach = Coach(self.path)
        after = self.coach.history_for_problem(self.problem_id)
        self.assertEqual(after, before)
        self.assertEqual(after["attempts"][0]["attempt"]["training_context"], context)
        old_tables = self.coach._db().execute("SELECT name FROM sqlite_schema WHERE type = 'table' AND name LIKE 'legacy_%'").fetchall()
        self.assertEqual(old_tables, [])

    def test_new_code_changes_assessment_version_without_changing_feedback(self) -> None:
        """Inputs: two source-code versions at one unchanged feedback revision.
        Outputs: distinct evidence fingerprints and unchanged feedback history.

        Logic: expose new proof identity to checkpoint replay without inventing feedback.
        Dependencies: native attempt projections and version-bound solution evidence.
        """
        original = self.coach.history(self.attempt_id)
        first = self.coach.record_solution(self.attempt_id, "first-code", 0,
                                           {"code": "return 1;", "language": "Java"})
        version_one = self.coach.history(self.attempt_id)["attempt"]["assessment_version"]
        self.coach.record_solution(self.attempt_id, "second-code", 0,
                                   {"code": "return 2;", "language": "Java"})
        after = self.coach.history(self.attempt_id)
        self.assertNotEqual(version_one, after["attempt"]["assessment_version"])
        self.assertEqual(after["attempt"]["revision"], original["attempt"]["revision"])
        self.assertEqual(after["revisions"], original["revisions"])
        self.assertEqual(after["attempt"]["assessment_version"], self.coach.history(self.attempt_id)["attempt"]["assessment_version"])
        self.assertEqual(self.coach.receipt("first-code"), first)

    def test_selection_context_uses_native_evidence_and_frozen_plan_order(self) -> None:
        """Inputs: a native selection note and one existing daily plan.
        Outputs: selection history with the saved continuation order.

        Logic: expose only selection evidence to scheduling without allocating practice.
        Dependencies: native evidence kinds, frozen plan items, and _selection_context.
        """
        selection = {"date": "2026-01-02", "problem_id": self.problem_id,
                     "primary_framework": "hash-table", "training_identity": "retest"}
        self.coach._db().execute("INSERT INTO history_evidence VALUES (?, ?, NULL, ?, ?, ?)",
                                 ("recorded-selection", self.problem_id, "2026-01-02T00:00:00+00:00",
                                  "selection", storage.canonical_json(selection)))
        self._note("ordinary-note", "This source is not an assignment.")
        plan = self.coach.get_plan("2026-01-01")
        before = self.coach._db().execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        context = self.coach._selection_context("2026-01-03")
        self.assertEqual(context["recent_plan"], [item["attempt_id"] for item in plan["items"]])
        self.assertIn(selection, context["history"])
        self.assertFalse(any(item.get("note") == "This source is not an assignment." for item in context["history"]))
        self.assertEqual(self.coach._db().execute("SELECT COUNT(*) FROM attempts").fetchone()[0], before)

    def test_unknown_problem_history_does_not_create_records(self) -> None:
        """Inputs: an absent canonical problem ID. Outputs: a read-only not-found error.

        Logic: retain the catalog and state when a history target is unknown.
        Dependencies: history_for_problem and the native storage boundary.
        """
        before = self.path.read_bytes()
        with self.assertRaises(CoachError) as raised:
            self.coach.history_for_problem("leetcode:999999")
        self.assertEqual(raised.exception.code, "not_found")
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
