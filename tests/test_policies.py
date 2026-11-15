"""Verify durable training scope, proposal activation, and shared enforcement."""

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.errors import CoachError
from algorithm_coach.service import Coach


class PolicyTests(unittest.TestCase):
    """Exercise policies through the public local service with synthetic records."""

    def setUp(self) -> None:
        """Create a clean private workspace.

        Inputs: None.
        Outputs: An initialized Coach and a submission counter.
        Logic: Isolate every test from real records and other policy revisions.
        Dependencies: tempfile, pathlib, and Coach.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "private" / "coach.sqlite3"
        self.coach = Coach(self.path)
        self.coach.initialize({"timezone": "UTC"})
        self.sequence = 0

    def tearDown(self) -> None:
        """Close the authority and discard synthetic data.

        Inputs: The test fixture.
        Outputs: None.
        Logic: Close open database handles before removing temporary files.
        Dependencies: Coach and tempfile.
        """
        self.coach.close()
        self.temp.cleanup()

    def _submission(self) -> str:
        """Allocate a unique synthetic action ID.

        Inputs: The fixture counter.
        Outputs: A stable ID for one test operation.
        Logic: Increment a local integer without using personal identifiers.
        Dependencies: None.
        """
        self.sequence += 1
        return f"synthetic-policy-{self.sequence}"

    def _propose(self, changes: dict) -> dict:
        """Create a proposal against the latest activation revision.

        Inputs: Explicit policy field changes.
        Outputs: The committed proposal receipt.
        Logic: Use a fixed start date unless the caller supplies one.
        Dependencies: Coach policy discovery and proposal operations.
        """
        revision = self.coach.get_policy("2026-01-02")["latest_revision"]
        return self.coach.propose_policy(
            {"effective_from": "2026-01-02", **changes}, revision, self._submission(),
        )

    def _activate(self, changes: dict) -> dict:
        """Activate the exact content of a synthetic proposal.

        Inputs: Policy changes.
        Outputs: The committed activation receipt.
        Logic: Bind activation to the proposal hash and its base revision.
        Dependencies: _propose and Coach.activate_policy.
        """
        proposal = self._propose(changes)
        return self.coach.activate_policy(proposal["proposal_id"], proposal["base_revision"],
                                          proposal["content_hash"], self._submission())

    def test_proposal_and_preview_do_not_activate_or_reserve_practice(self) -> None:
        """Keep negotiation separate from scheduling and activation.

        Inputs: An Easy tree policy proposal.
        Outputs: A useful preview, revision zero, and no saved plan or attempt.
        Logic: Compare SQLite record counts before and after repeated previews.
        Dependencies: Coach preview and read-only SQLite inspection.
        """
        proposal = self._propose({"topics_any": ["tree"], "difficulties": ["easy"]})
        first = self.coach.preview_policy(proposal["proposal_id"])
        second = self.coach.preview_policy(proposal["proposal_id"])
        self.assertEqual(first, second)
        self.assertGreater(first["eligible_count"], 0)
        self.assertEqual(self.coach.get_policy("2026-01-02")["revision"], 0)
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0], 0)
        finally:
            connection.close()

    def test_scope_survives_restart_and_applies_to_every_selected_problem(self) -> None:
        """Persist confirmed constraints beyond the current conversation.

        Inputs: A tree or graph policy with one excluded problem and a cap.
        Outputs: Only allowed Easy problems after a new service opens the database.
        Logic: Check scope membership and the cap independently of ranking.
        Dependencies: Coach persistence and candidate validation.
        """
        self._activate({"topics_any": ["tree", "graph"], "difficulties": ["easy"],
                        "excluded_problem_ids": ["leetcode:104"], "max_daily_count": 3})
        self.coach.close()
        self.coach = Coach(self.path)
        plan = self.coach.ensure_plan("2026-01-02")
        self.assertEqual(plan["policy_revision"], 1)
        self.assertLessEqual(len(plan["items"]), 3)
        self.assertGreater(len(plan["items"]), 0)
        for item in plan["items"]:
            self.assertTrue(set(item["problem"]["tags"]) & {"tree", "graph"})
            self.assertEqual(item["problem"]["difficulty"], "easy")
            self.assertNotEqual(item["problem"]["id"], "leetcode:104")

    def test_unknown_fields_ids_topics_and_empty_allowlists_are_rejected(self) -> None:
        """Reject unsupported scope instead of silently broadening it.

        Inputs: Malformed policy changes and unknown catalog references.
        Outputs: Domain errors and no activation.
        Logic: Try invalid contracts against an unchanged policy revision.
        Dependencies: Coach policy validation.
        """
        invalid = [
            {"topics_any": []}, {"difficulties": []}, {"problem_ids": []},
            {"topics_any": ["not-a-known-topic"]}, {"problem_ids": ["leetcode:999999"]},
            {"excluded_problem_ids": ["leetcode:999999"]}, {"difficulties": ["extreme"]},
            {"max_daily_count": True}, {"max_daily_count": 0}, {"user_confirmed": True},
            {"effective_from": "2026-02-30"}, {"effective_until": "2026-01-01"},
            {"preferred_topics": ["not-a-known-topic"]},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises(CoachError):
                    self._propose(changes)
        self.assertEqual(self.coach.get_policy("2026-01-02")["latest_revision"], 0)

    def test_activation_requires_exact_content_and_current_base(self) -> None:
        """Bind approval to a specific proposal and policy base.

        Inputs: Two competing proposals and an incorrect content hash.
        Outputs: Rejections for the wrong hash and the stale proposal.
        Logic: Activate one proposal and try to overwrite it from the old base.
        Dependencies: Coach content hashes and optimistic policy revisions.
        """
        first = self._propose({"topics_any": ["tree"]})
        second = self._propose({"topics_any": ["graph"]})
        with self.assertRaises(CoachError):
            self.coach.activate_policy(first["proposal_id"], 0, "0" * 64, self._submission())
        self.coach.activate_policy(first["proposal_id"], 0, first["content_hash"], self._submission())
        with self.assertRaises(CoachError):
            self.coach.activate_policy(second["proposal_id"], 0, second["content_hash"], self._submission())
        self.assertEqual(self.coach.get_policy("2026-01-02")["policy"]["topics_any"], ["tree"])

    def test_policy_operations_are_idempotent_before_revision_checks(self) -> None:
        """Allow exact retries after policy revision advancement.

        Inputs: Replayed proposal and activation operations.
        Outputs: Original receipts and one policy activation.
        Logic: Keep the original action IDs and request parameters for retries.
        Dependencies: Coach permanent submission receipts.
        """
        changes = {"effective_from": "2026-01-02", "topics_any": ["tree"]}
        proposal_id = self._submission()
        proposal = self.coach.propose_policy(changes, 0, proposal_id)
        operation_id = self._submission()
        applied = self.coach.activate_policy(proposal["proposal_id"], 0,
                                             proposal["content_hash"], operation_id)
        self.assertEqual(applied, self.coach.activate_policy(
            proposal["proposal_id"], 0, proposal["content_hash"], operation_id))
        self.assertEqual(proposal, self.coach.propose_policy(changes, 0, proposal_id))
        with self.assertRaises(CoachError):
            self.coach.propose_policy({**changes, "topics_any": ["graph"]}, 0, proposal_id)
        self.assertEqual(self.coach.get_policy("2026-01-02")["latest_revision"], 1)

    def test_outside_continuation_is_paused_without_changing_feedback(self) -> None:
        """Respect new scope without silently skipping old unfinished work.

        Inputs: D on an array problem and a later tree-only policy.
        Outputs: The old history remains D and tomorrow includes only tree work.
        Logic: Filter planning while continuing to accept factual feedback records.
        Dependencies: Coach plans, policy filtering, and feedback revisions.
        """
        plan = self.coach.ensure_plan("2026-01-01")
        item = next(item for item in plan["items"] if item["problem"]["id"] == "leetcode:1")
        self.coach.submit_feedback(item["attempt_id"], self._submission(), 0,
                                   {"result": "D", "elapsed_minutes": 20},
                                   occurred_at="2026-01-01T12:00:00+00:00")
        self._activate({"topics_any": ["tree"]})
        scoped = self.coach.ensure_plan("2026-01-02")
        self.assertNotIn(item["attempt_id"], [item["attempt_id"] for item in scoped["items"]])
        self.assertTrue(all("tree" in item["problem"]["tags"] for item in scoped["items"]))
        history = self.coach.history(item["attempt_id"])
        self.assertEqual(history["attempt"]["feedback"]["result"], "D")
        self.assertEqual(len(history["revisions"]), 1)
        self.coach.submit_feedback(item["attempt_id"], self._submission(), 1,
                                   {"elapsed_minutes": 25})
        self.assertEqual(self.coach.history(item["attempt_id"])["attempt"]["feedback"]["elapsed_minutes"], 25)

    def test_due_review_cannot_bypass_difficulty_scope(self) -> None:
        """Keep an out-of-scope retest pending rather than forcing it into a plan.

        Inputs: A Medium assisted result and a later Easy-only policy.
        Outputs: No Medium review in the plan and an unchanged pending record.
        Logic: Apply difficulty filtering to the review path as well as new work.
        Dependencies: Coach review scheduling and policy eligibility.
        """
        plan = self.coach.ensure_plan("2026-01-01")
        medium = next(item for item in plan["items"] if item["problem"]["difficulty"] == "medium")
        self.coach.submit_feedback(medium["attempt_id"], self._submission(), 0, {"result": "B"},
                                   occurred_at="2026-01-01T12:00:00+00:00")
        self._activate({"difficulties": ["easy"]})
        scoped = self.coach.ensure_plan("2026-01-02")
        self.assertTrue(all(item["problem"]["difficulty"] == "easy" for item in scoped["items"]))
        reviews = self.coach.learning_state()["reviews"]
        source = next(review for review in reviews if review["source_attempt_id"] == medium["attempt_id"])
        self.assertEqual(source["status"], "pending")

    def test_manual_redo_enforces_scope_and_explicit_daily_cap(self) -> None:
        """Prevent the manual scheduling path from bypassing policy limits.

        Inputs: A tree-only policy with two daily slots.
        Outputs: Rejection of outside work and extra reservations after the cap.
        Logic: Count reserved plan work and explicit new practices together.
        Dependencies: Coach.start_practice and shared policy checks.
        """
        self._activate({"topics_any": ["tree"], "max_daily_count": 2})
        with self.assertRaises(CoachError):
            self.coach.start_practice("leetcode:1", self._submission(), training_date="2026-01-02")
        self.coach.ensure_plan("2026-01-02")
        with self.assertRaises(CoachError):
            self.coach.start_practice("leetcode:104", self._submission(), training_date="2026-01-02")

    def test_partial_plan_reports_shortfall_without_widening_scope(self) -> None:
        """Allow a small valid plan instead of filling it with outside problems.

        Inputs: A one-problem scope and the default five-problem target.
        Outputs: One selected problem with explicit shortfall diagnostics.
        Logic: Treat capacity as a target or cap, never permission to widen scope.
        Dependencies: Coach planning diagnostics.
        """
        self._activate({"problem_ids": ["leetcode:104"]})
        plan = self.coach.ensure_plan("2026-01-02")
        self.assertEqual([item["problem"]["id"] for item in plan["items"]], ["leetcode:104"])
        self.assertEqual(plan["diagnostics"]["shortfall"], 4)

    def test_zero_available_candidates_do_not_freeze_an_empty_day(self) -> None:
        """Leave blocked dates available for a later valid retry.

        Inputs: A sole allowed problem that was just completed and is not due.
        Outputs: A blocked result, no saved next-day plan, and a valid due retest.
        Logic: Record capacity failure without publishing a misleading empty plan.
        Dependencies: Coach cooldown, plan persistence, and review timing.
        """
        self._activate({"problem_ids": ["leetcode:104"]})
        item = self.coach.ensure_plan("2026-01-02")["items"][0]
        self.coach.submit_feedback(item["attempt_id"], self._submission(), 0, {"result": "A"},
                                   occurred_at="2026-01-02T12:00:00+00:00")
        blocked = self.coach.ensure_plan("2026-01-03")
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["items"], [])
        with self.assertRaises(CoachError):
            self.coach.get_plan("2026-01-03")
        due = self.coach.ensure_plan("2026-01-05")
        self.assertEqual(due["items"][0]["problem"]["id"], "leetcode:104")
        self.assertNotEqual(due["items"][0]["attempt_id"], item["attempt_id"])

    def test_expiring_policy_resolves_previous_applicable_policy(self) -> None:
        """Expose the defined scope after a bounded policy expires.

        Inputs: A persistent tree policy and a later bounded graph policy.
        Outputs: Graph scope during the interval and tree scope afterward.
        Logic: Select the latest applicable activated revision for each date.
        Dependencies: Coach policy resolution and immutable activation history.
        """
        self._activate({"topics_any": ["tree"]})
        self._activate({"topics_any": ["graph"], "effective_from": "2026-01-05",
                        "effective_until": "2026-01-07"})
        during = self.coach.get_policy("2026-01-06")
        after = self.coach.get_policy("2026-01-08")
        self.assertEqual(during["revision"], 2)
        self.assertEqual(after["revision"], 1)
        self.assertEqual(after["latest_revision"], 2)
        self.assertEqual(after["policy"]["topics_any"], ["tree"])
        self.assertTrue(after["fallback"])

    def test_activation_does_not_rewrite_a_conflicting_published_plan(self) -> None:
        """Keep immutable plan membership when a new scope conflicts with it.

        Inputs: A published unrestricted plan and a conflicting same-date proposal.
        Outputs: Rejected activation and the same plan IDs and feedback.
        Logic: Require a later unpublished date rather than silently replacing work.
        Dependencies: Coach activation preflight and frozen plans.
        """
        before = self.coach.ensure_plan("2026-01-02")
        proposal = self._propose({"topics_any": ["tree"]})
        preview = self.coach.preview_policy(proposal["proposal_id"])
        self.assertFalse(preview["activation_allowed"])
        self.assertIn("plan_conflict", [blocker["code"] for blocker in preview["activation_blockers"]])
        with self.assertRaises(CoachError):
            self.coach.activate_policy(proposal["proposal_id"], 0,
                                        proposal["content_hash"], self._submission())
        after = self.coach.get_plan("2026-01-02")
        self.assertEqual([row["attempt_id"] for row in before["items"]],
                         [row["attempt_id"] for row in after["items"]])
        self.assertEqual(self.coach.get_policy("2026-01-02")["latest_revision"], 0)

    def test_metadata_changes_make_a_preview_stale(self) -> None:
        """Require a fresh proposal when its catalog context has changed.

        Inputs: A proposal followed by an append-only catalog import.
        Outputs: Stale diagnostics and rejection of the old activation.
        Logic: Bind activation to the catalog used for the reviewed preview.
        Dependencies: Coach proposal versions and catalog import.
        """
        proposal = self._propose({"topics_any": ["tree"]})
        self.coach.import_catalog([{"id": "leetcode:27", "title": "Remove Element", "difficulty": "easy",
                                    "tags": ["array", "two-pointers"],
                                    "url": "https://leetcode.com/problems/remove-element/"}], self._submission())
        self.assertTrue(self.coach.preview_policy(proposal["proposal_id"])["stale"])
        with self.assertRaises(CoachError):
            self.coach.activate_policy(proposal["proposal_id"], 0,
                                        proposal["content_hash"], self._submission())

    def test_config_changes_make_a_proposal_stale(self) -> None:
        """Keep a reviewed preview bound to its configuration context.

        Inputs: A proposal and a later daily-count change.
        Outputs: Rejection until the scope is proposed and reviewed again.
        Logic: Check configuration revision as well as policy revision.
        Dependencies: Coach configuration and activation preconditions.
        """
        proposal = self._propose({"topics_any": ["tree"]})
        current = self.coach.get_config()
        self.coach.update_config({"daily_count": 3}, current["revision"])
        with self.assertRaises(CoachError):
            self.coach.activate_policy(proposal["proposal_id"], 0,
                                        proposal["content_hash"], self._submission())

    def test_null_explicitly_removes_a_scope_filter(self) -> None:
        """Preserve patch semantics without treating empty lists as unrestricted.

        Inputs: A tree-only scope, an inherited update, and explicit null.
        Outputs: Retained scope on omission and unrestricted topics on null.
        Logic: Separate inheritance from explicit removal of a constraint.
        Dependencies: Coach proposal normalization.
        """
        self._activate({"topics_any": ["tree"]})
        inherited = self._propose({"name": "Same trees"})
        self.assertEqual(inherited["body"]["topics_any"], ["tree"])
        unrestricted = self._propose({"topics_any": None})
        self.assertIsNone(unrestricted["body"]["topics_any"])

    def test_plan_cannot_allocate_extra_slots_after_manual_reservations(self) -> None:
        """Apply the hard daily cap regardless of which entry point runs first.

        Inputs: Two explicit redos of one problem under a two-practice cap.
        Outputs: No additional reserved practice when a plan is generated.
        Logic: Count unique practice IDs rather than unique problem IDs.
        Dependencies: Coach manual allocation and final plan capacity checks.
        """
        self._activate({"topics_any": ["tree"], "max_daily_count": 2})
        for index in range(2):
            self.coach.start_practice("leetcode:104", f"manual-repeat-{index}", training_date="2026-01-02")
        plan = self.coach.ensure_plan("2026-01-02")
        self.assertLessEqual(len(plan["items"]), 2)
        self.assertEqual(len(self.coach.learning_state()["attempts"]), 2)
        self.assertGreater(plan["diagnostics"]["shortfall"], 0)

    def test_activation_cannot_lower_cap_below_existing_manual_work(self) -> None:
        """Reject a new hard limit that existing dated reservations already exceed.

        Inputs: Two manual practices and a proposed one-practice cap.
        Outputs: A conflict and the unchanged activation revision.
        Logic: Preflight manual reservations as well as frozen daily plans.
        Dependencies: Coach activation safety checks.
        """
        for index in range(2):
            self.coach.start_practice("leetcode:104", f"before-policy-{index}", training_date="2026-01-02")
        proposal = self._propose({"max_daily_count": 1})
        with self.assertRaises(CoachError):
            self.coach.activate_policy(proposal["proposal_id"], 0, proposal["content_hash"], self._submission())
        self.assertEqual(self.coach.get_policy("2026-01-02")["latest_revision"], 0)

    def test_due_defer_is_visible_when_paused_by_scope(self) -> None:
        """Keep deferred unfinished work visible after its resume date.

        Inputs: An array practice deferred until a tree-only policy starts.
        Outputs: A scope-paused backlog entry while its feedback remains E.
        Logic: Report policy exclusion without changing a user scheduling decision.
        Dependencies: Coach policy preview and backlog diagnostics.
        """
        item = next(item for item in self.coach.ensure_plan("2026-01-01")["items"]
                    if item["problem"]["id"] == "leetcode:1")
        self.coach.submit_feedback(item["attempt_id"], self._submission(), 0,
                                   {"result": "E", "defer_until": "2026-01-02"},
                                   occurred_at="2026-01-01T12:00:00+00:00")
        proposal = self._propose({"topics_any": ["tree"]})
        preview = self.coach.preview_policy(proposal["proposal_id"])
        self.assertIn(item["attempt_id"], [row["attempt_id"] for row in preview["paused_backlog"]])
        self.assertEqual(self.coach.history(item["attempt_id"])["attempt"]["feedback"]["result"], "E")

    def test_preview_exposes_expiry_and_rejects_an_inactive_date(self) -> None:
        """Make the scope after expiry part of the reviewable proposal.

        Inputs: A policy bounded to one week and an outside preview date.
        Outputs: Explicit baseline fallback and an inactive-policy error outside its range.
        Logic: Do not present an out-of-date policy as the scope for another day.
        Dependencies: Coach preview and date-effective policy resolution.
        """
        proposal = self._propose({"topics_any": ["tree"], "effective_until": "2026-01-08"})
        preview = self.coach.preview_policy(proposal["proposal_id"])
        fallback = preview["expiry_fallback"]
        self.assertEqual(fallback["training_date"], "2026-01-09")
        self.assertEqual(fallback["revision"], 0)
        self.assertIsNone(fallback["policy"]["topics_any"])
        with self.assertRaises(CoachError):
            self.coach.preview_policy(proposal["proposal_id"], "2026-01-01")

    def test_failed_activation_receipt_rolls_back_the_policy_version(self) -> None:
        """Keep activation atomic with its acknowledgement.

        Inputs: A valid proposal and a failing final receipt insertion.
        Outputs: No activated policy or receipt, followed by a successful retry.
        Logic: Fail after the policy row is inserted inside the real transaction.
        Dependencies: SQLite triggers and Coach permanent receipts.
        """
        proposal = self._propose({"topics_any": ["tree"]})
        action = self._submission()
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("CREATE TRIGGER fail_policy_receipt BEFORE INSERT ON submissions "
                               "WHEN NEW.operation = 'activate_policy' "
                               "BEGIN SELECT RAISE(ABORT, 'synthetic activation failure'); END")
            connection.commit()
            with self.assertRaises(CoachError):
                self.coach.activate_policy(proposal["proposal_id"], 0, proposal["content_hash"], action)
            self.assertEqual(self.coach.get_policy("2026-01-02")["latest_revision"], 0)
            with self.assertRaises(CoachError):
                self.coach.receipt(action)
            connection.execute("DROP TRIGGER fail_policy_receipt")
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(self.coach.activate_policy(proposal["proposal_id"], 0,
                                                     proposal["content_hash"], action)["revision"], 1)

    def test_soft_policy_change_respects_a_frozen_plans_original_capacity(self) -> None:
        """Keep later plan targets from invalidating earlier frozen assignments.

        Inputs: A five-problem frozen plan, a smaller current target, and a soft preference.
        Outputs: Allowed activation, five preserved old items, and a smaller next plan.
        Logic: Check old membership against its saved config plus new hard policy limits.
        Dependencies: Coach config snapshots and frozen-plan policy preflight.
        """
        before = self.coach.ensure_plan("2026-01-02")
        self.assertEqual(len(before["items"]), 5)
        config = self.coach.get_config()
        self.coach.update_config({"daily_count": 3}, config["revision"])
        proposal = self._propose({"preferred_topics": ["tree"]})
        self.assertTrue(self.coach.preview_policy(proposal["proposal_id"])["activation_allowed"])
        self.coach.activate_policy(proposal["proposal_id"], 0, proposal["content_hash"], self._submission())
        after = self.coach.get_plan("2026-01-02")
        self.assertEqual([row["attempt_id"] for row in before["items"]],
                         [row["attempt_id"] for row in after["items"]])
        self.assertTrue(after["current_policy_match"])
        self.assertEqual(after["config_snapshot"]["daily_count"], 5)
        self.assertEqual(len(self.coach.ensure_plan("2026-01-03")["items"]), 3)


if __name__ == "__main__":
    unittest.main()
