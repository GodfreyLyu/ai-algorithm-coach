"""Test interview rules with synthetic contexts and no private training data."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.errors import CoachError
from algorithm_coach.core.policies import default_policy
from algorithm_coach.core.rules import default_config, derive_learning_state, merge_feedback, select_candidates, validate_config
from algorithm_coach.core.training_profile import assessment_version, learning_outcome, primary_framework, timebox, validate_training_context


def _catalog() -> list[dict]:
    """Build public-shaped synthetic metadata with distinct frameworks.

    Inputs: None.
    Outputs: Seven independent metadata entries.
    Logic: Avoid importing real training records into fixtures.
    Dependencies: None.
    """
    frames = ("hash-table", "linked-list", "binary-search", "stack", "tree", "graph", "dynamic-programming")
    return [{"id": f"leetcode:{number}", "title": f"Synthetic problem {number}", "difficulty": "medium", "tags": [frame], "url": f"https://leetcode.com/problems/synthetic-{number}/"} for number, frame in enumerate(frames, 1)]


def _config() -> dict:
    """Select the interview profile for synthetic rule tests.

    Inputs: None.
    Outputs: Valid profile settings.
    Logic: Leave the standard profile unchanged elsewhere.
    Dependencies: validate_config.
    """
    return validate_config({"training_profile": "tokyo-interview-v1", "daily_count": 6, "timezone": "Asia/Tokyo"})


def _research(catalog: list[dict]) -> dict:
    """Supply explicit host research for synthetic candidates.

    Inputs: Synthetic metadata.
    Outputs: Candidate context keyed by public problem ID.
    Logic: Scores are relative training inputs, not claimed company frequency.
    Dependencies: None.
    """
    return {problem["id"]: {"primary_framework": problem["tags"][0], "score": [35, 25, 12, 8, 4], "source_verified": True, "source_verification": {"official": {"url": problem["url"], "checked_date": "2026-01-01"}}, "targeted_gap": "Synthetic confirmed gap"} for problem in catalog}


def _attempt(identity: str, day: str, result: str | None = "A", proof: bool = True) -> dict:
    """Create one effective synthetic retest attempt.

    Inputs: Attempt ID, occurrence date, result, and proof availability.
    Outputs: An independent attempt dictionary.
    Logic: Distinguish missing proof from false proof.
    Dependencies: None.
    """
    feedback = {"result": result, "assistance": "none" if result == "A" else "solution" if result == "C" else None, "elapsed_minutes": 12, "proficiency": 3}
    return {"id": identity, "problem_id": "leetcode:1", "language": "Java", "kind": "review", "planned_date": day, "practice_date": day, "revision": 1, "feedback": feedback, "assessment": {field: True for field in ("invariant", "correctness", "complexity", "boundary")} if proof else {}, "training_context": {"training_identity": "retest", "primary_framework": "hash-table", "source_verified": True, "source_verification": {"official": {"url": "https://leetcode.com/problems/synthetic-1/", "checked_date": "2026-01-01"}}}}


def _checkpoint(records: list[dict], **changes: object) -> dict:
    """Capture a confirmed native learning boundary for synthetic attempts.

    Inputs: Effective attempts and explicit state overrides.
    Outputs: A partial-coverage checkpoint with bound outcome and proof versions.
    Logic: Preserve confirmed state independently of a later feedback correction.
    Dependencies: Pure rules, assessment_version, and deepcopy.
    """
    state = deepcopy(derive_learning_state(records, _config(), _catalog())["problems"][0])
    state.update(changes)
    return {"state": state, "rule_version": "tokyo-interview-v1", "evidence_coverage": "partial",
            "feedback_revisions": {item["id"]: item["revision"] for item in records},
            "assessment_versions": {item["id"]: assessment_version(item) for item in records},
            "outcomes": {item["id"]: learning_outcome(item) for item in records}}



class InterviewProfileTests(unittest.TestCase):
    """Verify allocation and learning invariants in the versioned profile."""

    def test_standard_profile_keeps_its_existing_defaults(self) -> None:
        """Preserve the baseline selection path.

        Inputs: Default settings and the synthetic catalog.
        Outputs: Five baseline candidates and an explicit standard profile.
        Logic: Profile adoption must not change unrelated existing workspaces.
        Dependencies: default_config and select_candidates.
        """
        self.assertEqual(default_config()["training_profile"], "standard")
        self.assertEqual(len(select_candidates(_catalog(), [], default_config(), "2026-01-05")), 5)
        with self.assertRaises(CoachError):
            validate_config({"training_profile": []})

    def test_fifth_is_normal_and_sixth_needs_a_reason(self) -> None:
        """Keep one ordinary supplement and a bounded optional second one.

        Inputs: Seven distinct candidates with explicit research.
        Outputs: Five items, then six when a remaining candidate is justified.
        Logic: A six-item maximum does not become a fixed six-item quota.
        Dependencies: select_candidates.
        """
        catalog = _catalog()
        research = _research(catalog)
        first = select_candidates(catalog, [], _config(), "2026-01-05", selection_context={"candidates": research})
        self.assertEqual(len(first), 5)
        self.assertEqual([item["daily_role"] for item in first], ["base"] * 4 + ["supplement"])
        research["leetcode:6"]["sixth_justification"] = "Distinct useful framework fits the remaining budget."
        second = select_candidates(catalog, [], _config(), "2026-01-05", selection_context={"candidates": research})
        self.assertEqual(len(second), 6)
        self.assertEqual(second[-1]["daily_role"], "supplement")
        self.assertEqual(sum(item["timebox"]["min"] for item in second), 120)

    def test_backlog_preserves_latest_order_identity_and_round(self) -> None:
        """Continue six known rounds without new allocations or extra counts.

        Inputs: Six unfinished attempts in the recent published order.
        Outputs: The same IDs and original retest timeboxes in that order.
        Logic: Current D status must not displace another recent base item.
        Dependencies: select_candidates and deepcopy.
        """
        catalog = _catalog()
        attempts = []
        for number, problem in enumerate(catalog[:6], 1):
            item = _attempt(f"pending-{number}", "2026-01-01", None)
            item["problem_id"] = problem["id"]
            item["training_context"]["primary_framework"] = problem["tags"][0]
            attempts.append(item)
        attempts[4]["feedback"]["result"] = "D"
        before = deepcopy(attempts)
        expected = [item["id"] for item in attempts]
        chosen = select_candidates(catalog, attempts, _config(), "2026-01-05", selection_context={"recent_plan": expected})
        self.assertEqual([item["attempt_id"] for item in chosen], expected)
        self.assertTrue(all(item["timebox"]["max"] == 15 for item in chosen))
        self.assertEqual(attempts, before)

    def test_scope_and_same_day_framework_are_hard_constraints(self) -> None:
        """Pause conflicts without allocating outside scope or changing history.

        Inputs: Duplicate frameworks and one excluded problem.
        Outputs: Distinct eligible frameworks and a truthful shortfall.
        Logic: Neither a quota nor a score overrides the active hard scope.
        Dependencies: select_candidates and default_policy.
        """
        catalog = _catalog()
        research = _research(catalog)
        research["leetcode:2"]["primary_framework"] = "hash-table"
        policy = {**default_policy(), "excluded_problem_ids": ["leetcode:7"], "max_daily_count": 4}
        chosen = select_candidates(catalog, [], _config(), "2026-01-05", policy=policy, selection_context={"candidates": research})
        self.assertLessEqual(len(chosen), 4)
        self.assertNotIn("leetcode:7", {item["problem_id"] for item in chosen})
        self.assertEqual(len({item["primary_framework"] for item in chosen}), len(chosen))

    def test_new_weekly_repeats_need_a_different_technique_reason(self) -> None:
        """Apply weekly de-duplication to new work while keeping explicit exceptions.

        Inputs: A previously seen framework and one exact previously recommended ID.
        Outputs: The exact repeat excluded and the framework repeat explained.
        Logic: An explanation permits a different technique, not the same new problem.
        Dependencies: select_candidates.
        """
        catalog = _catalog()
        research = _research(catalog)
        history = [{"date": "2026-01-05", "problem_id": "leetcode:1", "primary_framework": "hash-table"}]
        research["leetcode:2"]["primary_framework"] = "hash-table"
        chosen = select_candidates(catalog, [], _config(), "2026-01-06", selection_context={"candidates": research, "history": history})
        self.assertNotIn("leetcode:1", {item["problem_id"] for item in chosen})
        self.assertNotIn("leetcode:2", {item["problem_id"] for item in chosen})
        research["leetcode:2"]["weekly_repeat_justification"] = "Use a distinct boundary technique after other frameworks."
        chosen = select_candidates(catalog[:2], [], _config(), "2026-01-06", selection_context={"candidates": research, "history": history})
        self.assertEqual([item["problem_id"] for item in chosen], ["leetcode:2"])

    def test_stability_requires_separate_dates_and_complete_evidence(self) -> None:
        """Keep AC, independent completion, and stable performance distinct.

        Inputs: Self-reports, same-day redos, and two qualifying dated retests.
        Outputs: Stable transfer eligibility only for the last case.
        Logic: A missing oral or boundary check cannot be filled by model agreement.
        Dependencies: derive_learning_state.
        """
        first = _attempt("first", "2026-01-01")
        second = _attempt("second", "2026-01-08")
        self.assertFalse(derive_learning_state([_attempt("unknown", "2026-01-01", proof=False)], _config(), _catalog())["problems"][0]["transfer_eligible"])
        same = deepcopy(second)
        same["planned_date"] = same["practice_date"] = "2026-01-01"
        self.assertFalse(derive_learning_state([first, same], _config(), _catalog())["problems"][0]["transfer_eligible"])
        state = derive_learning_state([first, second], _config(), _catalog())["problems"][0]
        self.assertTrue(state["transfer_eligible"])
        self.assertEqual(state["consecutive_stable_passes"], 2)
        self.assertEqual(state["review_interval_range"], [14, 30])

    def test_checkpoint_survives_a_new_unfinished_round(self) -> None:
        """Preserve confirmed scheduling when a recommendation has no result.

        Inputs: A checkpoint with an exact due date and a separate pending review.
        Outputs: Unchanged due date, stability, and review count.
        Logic: Recommendations and continuation do not create practice evidence.
        Dependencies: derive_learning_state and native checkpoints.
        """
        old = _attempt("old", "2026-01-01")
        checkpoint = _checkpoint([old], review_due="2026-01-24", consecutive_stable_passes=2,
                                 transfer_eligible=True, mastery_status="stable", review_count=7)
        old["learning_checkpoint"] = checkpoint
        pending = _attempt("pending", "2026-01-08", None)
        pending["revision"] = 0
        state = derive_learning_state([old, pending], _config(), _catalog())["problems"][0]
        self.assertEqual(state["review_due"], "2026-01-24")
        self.assertEqual(state["review_count"], 7)
        self.assertEqual(state["consecutive_stable_passes"], 2)
        self.assertEqual(state["completed_count"], 1)
        self.assertEqual(state["evidence_coverage"], "partial")

    def test_earlier_checkpoint_correction_requires_reconciliation(self) -> None:
        """Avoid scheduling from an incomplete replay after an earlier correction.

        Inputs: A confirmed checkpoint and an earlier performance changed to assisted.
        Outputs: Unconfirmed stability, no asserted due date, and the prior decision.
        Logic: The next due date must not be rebuilt from only the changed old event.
        Dependencies: derive_learning_state and deepcopy.
        """
        old = _attempt("old", "2026-01-01")
        latest = _attempt("latest", "2026-01-08")
        checkpoint = _checkpoint([old, latest], review_due="2026-01-31", review_count=7)
        old["feedback"]["result"] = "C"
        old["feedback"]["assistance"] = "solution"
        old["revision"] = 2
        latest["learning_checkpoint"] = checkpoint
        before = deepcopy((old, latest))
        state = derive_learning_state([old, latest], _config(), _catalog())["problems"][0]
        self.assertTrue(state["reconciliation_required"])
        self.assertIsNone(state["review_due"])
        self.assertIsNone(state["review_source_attempt_id"])
        self.assertEqual(state["consecutive_stable_passes"], 0)
        self.assertFalse(state["transfer_eligible"])
        self.assertEqual(state["prior_review_due"], "2026-01-31")
        self.assertEqual(state["independent_count"], 1)
        self.assertEqual((old, latest), before)

    def test_checkpoint_completion_retraction_revokes_stability(self) -> None:
        """Honor current-round corrections that remove completion evidence.

        Inputs: A confirmed stable round corrected to unknown, defer, or skip.
        Outputs: No retained stable claim or due date; unknown can resume the round.
        Logic: A bound disposition cannot override a newer feedback revision.
        Dependencies: derive_learning_state and select_candidates.
        """
        for result in (None, "E", "F"):
            with self.subTest(result=result):
                current = _attempt("current", "2026-01-08")
                checkpoint = _checkpoint([current], review_due="2026-01-31", review_count=7,
                                         consecutive_stable_passes=2, transfer_eligible=True)
                current["learning_checkpoint"] = checkpoint
                current["feedback"]["result"] = result
                current["revision"] = 2
                current["training_context"].update(disposition="completed", disposition_revision=1)
                state = derive_learning_state([current], _config(), _catalog())["problems"][0]
                self.assertEqual(state["consecutive_stable_passes"], 0)
                self.assertFalse(state["transfer_eligible"])
                self.assertIsNone(state["review_due"])
                self.assertEqual(state["completed_count"], 0)
                selected = select_candidates(_catalog(), [current], _config(), "2026-01-09")
                self.assertEqual(len(selected), 0 if result == "F" else 1)

    def test_regression_resets_stability_and_shortens_review(self) -> None:
        """React to new confirmed dependence without rewriting historical evidence.

        Inputs: Two stable retests followed by a separate answer-assisted attempt.
        Outputs: A reset streak and a one-to-three-day review band.
        Logic: Only new confirmed performance changes the next review decision.
        Dependencies: derive_learning_state.
        """
        attempts = [_attempt("one", "2026-01-01"), _attempt("two", "2026-01-08"), _attempt("three", "2026-01-09", "C")]
        state = derive_learning_state(attempts, _config(), _catalog())["problems"][0]
        self.assertEqual(state["consecutive_stable_passes"], 0)
        self.assertEqual(state["review_interval_range"], [1, 3])
        self.assertFalse(state["transfer_eligible"])
        self.assertEqual(len(state["evidence"]), 3)

    def test_same_day_answer_rewrite_cannot_seed_stability(self) -> None:
        """Keep an answer-assisted rewrite in the learning-check category.

        Inputs: An assisted attempt, an A rewrite that day, and a later independent A.
        Outputs: One stable pass and no duplicated review count for the rewrite.
        Logic: A new attempt ID cannot erase known same-day answer dependence.
        Dependencies: derive_learning_state.
        """
        assisted = _attempt("a-assisted", "2026-01-01", "C")
        rewrite = _attempt("b-rewrite", "2026-01-01")
        later = _attempt("later", "2026-01-08")
        state = derive_learning_state([assisted, rewrite, later], _config(), _catalog())["problems"][0]
        self.assertEqual(state["consecutive_stable_passes"], 1)
        self.assertEqual(state["review_count"], 2)
        self.assertFalse(state["transfer_eligible"])

    def test_transfer_requires_recorded_source_stability(self) -> None:
        """Reject premature transfer while allowing eligible framework practice.

        Inputs: A proposed transfer with and without qualifying source evidence.
        Outputs: No transfer before the stable gate, then a 15-to-25-minute item.
        Logic: The host cannot bypass memory gates by labelling a new candidate.
        Dependencies: select_candidates and derive_learning_state.
        """
        catalog = _catalog()
        research = {"leetcode:2": {**_research(catalog)["leetcode:2"], "transfer_from": "leetcode:1", "primary_framework": "hash-table", "transfer_change": "A changed input condition tests the same framework."}}
        first = select_candidates(catalog, [], _config(), "2026-01-10", selection_context={"candidates": research})
        self.assertEqual(first, [])
        attempts = [_attempt("one", "2026-01-01"), _attempt("two", "2026-01-08")]
        chosen = select_candidates(catalog, attempts, _config(), "2026-01-10", selection_context={"candidates": research})
        self.assertEqual(chosen[0]["training_identity"], "transfer")
        self.assertEqual(chosen[0]["timebox"]["max"], 25)

    def test_native_dispositions_do_not_invent_ac_or_backlog(self) -> None:
        """Keep confirmed lifecycle facts separate from an invented A result.

        Inputs: Completed or evidence-only records without a result enum.
        Outputs: No continuation for either closed native record.
        Logic: Native dispositions do not assert independent completion.
        Dependencies: select_candidates.
        """
        for disposition in ("completed", "record_only"):
            with self.subTest(disposition=disposition):
                attempt = _attempt("record", "2026-01-01", None)
                attempt["training_context"].update(disposition=disposition, disposition_revision=1)
                self.assertEqual(select_candidates(_catalog(), [attempt], _config(), "2026-01-05"), [])

    def test_canonical_identity_keeps_the_original_timebox(self) -> None:
        """Use exact current-schema identities for practice budgets.

        Inputs: Canonical new, retest, and transfer identities.
        Outputs: Their documented boxes and an overtime retest decision.
        Logic: A retest remains bounded by fifteen minutes during continuation.
        Dependencies: timebox and derive_learning_state.
        """
        self.assertEqual((timebox("retest")["min"], timebox("retest")["max"]), (10, 15))
        self.assertEqual((timebox("transfer")["min"], timebox("transfer")["max"]), (15, 25))
        self.assertEqual(timebox("new")["max"], 30)
        late = _attempt("late", "2026-01-01")
        late["feedback"]["elapsed_minutes"] = 20
        state = derive_learning_state([late], _config(), _catalog())["problems"][0]
        self.assertEqual(state["review_interval_range"], [3, 7])
        self.assertEqual(state["consecutive_stable_passes"], 0)

    def test_research_cannot_change_practice_facts(self) -> None:
        """Reject practice facts in a research-only write channel.

        Inputs: Outcome, checkpoint, identity, and original-date override attempts.
        Outputs: Validation errors without converting recommendations into completion.
        Logic: Validated feedback and native context establish these protected facts.
        Dependencies: validate_training_context and select_candidates.
        """
        attempts = [_attempt("pending", "2026-01-01", None)]
        protected = {"disposition": "completed", "disposition_revision": 100,
                     "learning_checkpoint": {}, "consecutive_stable_passes": 2,
                     "training_identity": "new", "original_recommendation_date": "2026-01-05"}
        for field, value in protected.items():
            with self.subTest(field=field):
                with self.assertRaises(CoachError):
                    validate_training_context({field: value})
        chosen = select_candidates(_catalog(), attempts, _config(), "2026-01-05", selection_context={"candidates": {"leetcode:1": {"targeted_gap": "Fresh research note."}}})
        self.assertEqual(chosen[0]["attempt_id"], "pending")
        self.assertEqual(chosen[0]["training_identity"], "retest")
        self.assertEqual(chosen[0]["original_recommendation_date"], "2026-01-01")

    def test_original_continuation_context_wins_over_global_research(self) -> None:
        """Keep one round's framework and identity when generic research differs.

        Inputs: An original retest and a generic candidate framework update.
        Outputs: The original round, framework, date, and15-minute ceiling.
        Logic: Problem-level metadata cannot silently recategorize existing work.
        Dependencies: select_candidates and _research.
        """
        attempt = _attempt("pending", "2026-01-01", None)
        attempt["training_context"]["training_identity"] = "retest"
        global_context = _research(_catalog())["leetcode:1"]
        global_context["primary_framework"] = "graph"
        chosen = select_candidates(_catalog(), [attempt], _config(), "2026-01-05", selection_context={"candidates": {"leetcode:1": global_context}})
        self.assertEqual(chosen[0]["primary_framework"], "hash-table")
        self.assertEqual(chosen[0]["timebox"]["max"], 15)

    def test_context_and_feedback_validation_preserve_unknowns(self) -> None:
        """Validate structured evidence without accepting impossible claims.

        Inputs: Weighted scores, contradictory hint data, and missing oral fields.
        Outputs: Validation errors or explicit unanswered proof flags.
        Logic: Do not let a supplied result erase known assistance or invent proof.
        Dependencies: validate_training_context, merge_feedback and timebox.
        """
        for scores in ([41, 0, 0, 0, 0], [True, 0, 0, 0, 0], [1, 2]):
            with self.assertRaises(CoachError):
                validate_training_context({"score": scores})
        with self.assertRaises(CoachError):
            merge_feedback(None, {"result": "A", "hint_level": "key"})
        feedback = merge_feedback(None, {"result": "D", "hint_level": "minor", "closed_book_minutes": 10})
        self.assertEqual(feedback["assistance"], "hint")
        self.assertIsNone(feedback["can_explain_complexity"])
        self.assertEqual(timebox("retest")["max"], 15)
        self.assertEqual(primary_framework({"tags": []}, context={"framework": "二分答案的可行性判断"}), "binary-search")


if __name__ == "__main__":
    unittest.main()
