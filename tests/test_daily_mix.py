"""Test configured daily category slots with synthetic records and temporary stores."""

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from algorithm_coach.errors import CoachError
from algorithm_coach.core.policies import default_policy
from algorithm_coach.core.rules import select_candidates, select_with_diagnostics, validate_config
from algorithm_coach.service import Coach
import test_training_profile as fixtures

WEAK_NEW = {"slots": [{"category": "weak", "count": 2}, {"category": "new", "count": 1}]}


def _mix(*pairs: tuple[str, int], continuation: str | None = None) -> dict:
    """Build a daily_mix value from ordered category counts.

    Inputs: Category and count pairs, and an optional continuation mode.
    Outputs: A daily_mix object.
    Logic: Keep slot order as given because order is fill priority.
    Dependencies: None.
    """
    mix = {"slots": [{"category": category, "count": count} for category, count in pairs]}
    if continuation is not None:
        mix["continuation"] = continuation
    return mix


def _profile(count: int, mix: dict | None) -> dict:
    """Return validated interview settings with an optional mix.

    Inputs: The daily count and a daily_mix value.
    Outputs: Normalized settings.
    Logic: Use the synthetic Tokyo profile configuration.
    Dependencies: validate_config.
    """
    return validate_config({"training_profile": "tokyo-interview-v1", "daily_count": count,
                            "timezone": "Asia/Tokyo", "daily_mix": mix})


def _record(identity: str, number: int, day: str, result: str | None, language: str = "Java") -> dict:
    """Create one synthetic attempt for a numbered catalog problem.

    Inputs: Attempt ID, problem number, date, result, and language.
    Outputs: An attempt whose framework matches the synthetic problem tag.
    Logic: Reuse the profile fixture and change only identity fields.
    Dependencies: test_training_profile fixtures.
    """
    attempt = fixtures._attempt(identity, day, result)
    attempt["problem_id"] = f"leetcode:{number}"
    attempt["language"] = language
    attempt["training_context"]["primary_framework"] = fixtures._catalog()[number - 1]["tags"][0]
    if result is None:
        attempt["feedback"] = None
    return attempt


def _categories(selected: list[dict]) -> list[tuple[str, str]]:
    """Summarize interview candidates by problem and mix category.

    Inputs: Selected interview candidates.
    Outputs: Ordered problem and category pairs.
    Logic: Keep assertions short and readable.
    Dependencies: None.
    """
    return [(item["problem_id"], item["mix_category"]) for item in selected]


class DailyMixRuleTests(unittest.TestCase):
    """Verify category allocation rules with pure synthetic inputs."""

    def setUp(self) -> None:
        """Prepare a synthetic catalog and research.

        Inputs: None.
        Outputs: Catalog and researched candidates on the fixture.
        Logic: Every candidate has verified sources and a distinct framework.
        Dependencies: test_training_profile fixtures.
        """
        self.catalog = fixtures._catalog()
        self.context = {"candidates": fixtures._research(self.catalog)}

    def _select(self, attempts: list[dict], settings: dict, day: str = "2026-02-15", policy: dict | None = None) -> tuple:
        """Run mixed selection for one date.

        Inputs: Attempts, settings, date, and an optional policy.
        Outputs: Candidates and diagnostics.
        Logic: Use the public diagnostics entry point.
        Dependencies: select_with_diagnostics.
        """
        return select_with_diagnostics(self.catalog, attempts, settings, day, policy=policy, selection_context=self.context)

    def test_without_mix_both_profiles_keep_original_selection(self) -> None:
        """Keep the original selectors when no mix is configured.

        Inputs: Default settings for both profiles and one due retest.
        Outputs: The same candidates as select_candidates and no diagnostics.
        Logic: A null mix must not route through the new allocator.
        Dependencies: select_candidates and select_with_diagnostics.
        """
        attempts = [_record("a1", 1, "2026-01-01", "C")]
        for settings in (_profile(5, None), validate_config({"daily_count": 5})):
            expected = select_candidates(self.catalog, attempts, settings, "2026-01-05", selection_context=self.context)
            chosen, diagnostics = select_with_diagnostics(self.catalog, attempts, settings, "2026-01-05", selection_context=self.context)
            self.assertEqual(chosen, expected)
            self.assertIsNone(diagnostics)
            self.assertNotIn("daily_mix", settings)

    def test_two_weak_and_one_new(self) -> None:
        """Fill two recorded weaknesses and one unpracticed problem.

        Inputs: Two due assisted results and unpracticed researched problems.
        Outputs: Exactly two weak retests and one new problem.
        Logic: Weak slots require explicit feedback evidence and a due date.
        Dependencies: _select.
        """
        attempts = [_record("a1", 1, "2026-02-10", "C"), _record("a2", 2, "2026-02-11", "B")]
        chosen, diagnostics = self._select(attempts, _profile(3, WEAK_NEW))
        self.assertEqual(_categories(chosen), [("leetcode:1", "weak"), ("leetcode:2", "weak"), ("leetcode:3", "new")])
        self.assertEqual([item["training_identity"] for item in chosen], ["retest", "retest", "new"])
        self.assertEqual(diagnostics["category_shortfalls"], [])

    def test_five_slot_mix_with_fill_unused(self) -> None:
        """Let continuation fill a weak shortfall only in fill_unused mode.

        Inputs: Two pending attempts, one weak, one review, and new candidates.
        Outputs: Five items and a reported weak shortfall of one.
        Logic: Continuation fills the unused slot but does not count as weak.
        Dependencies: _select.
        """
        attempts = [_record("weak", 1, "2026-02-10", "C"), _record("stable", 2, "2026-01-01", "A"),
                    _record("open-3", 3, "2026-02-14", None), _record("open-4", 4, "2026-02-14", None)]
        mix = _mix(("continue", 1), ("weak", 2), ("review", 1), ("new", 1), continuation="fill_unused")
        chosen, diagnostics = self._select(attempts, _profile(5, mix))
        self.assertEqual(_categories(chosen), [("leetcode:3", "continue"), ("leetcode:1", "weak"), ("leetcode:2", "review"),
                                               ("leetcode:5", "new"), ("leetcode:4", "continue")])
        shortfall = diagnostics["category_shortfalls"]
        self.assertEqual([(item["category"], item["missing"]) for item in shortfall], [("weak", 1)])
        self.assertTrue(diagnostics["allocation"][-1]["fills_unused"])
        dedicated = {**mix, "continuation": "dedicated"}
        chosen, diagnostics = self._select(attempts, _profile(5, dedicated))
        self.assertEqual(len(chosen), 4)
        self.assertEqual([item["problem_id"] for item in diagnostics["unallocated_backlog"]], ["leetcode:4"])

    def test_invalid_mixes_and_schedule_fields_are_rejected(self) -> None:
        """Reject malformed allocations, times, and timezones.

        Inputs: Mismatched sums, unknown or repeated categories, bad counts, and bad times.
        Outputs: Validation errors for each value.
        Logic: Invalid settings never reach selection.
        Dependencies: validate_config.
        """
        invalid = [
            {"daily_count": 3, "daily_mix": _mix(("weak", 2))},
            {"daily_count": 2, "daily_mix": _mix(("new", 1), ("new", 1))},
            {"daily_count": 1, "daily_mix": _mix(("transfer", 1))},
            {"daily_count": 1, "daily_mix": _mix(("new", True))},
            {"daily_count": 1, "daily_mix": _mix(("new", -1))},
            {"daily_count": 1, "daily_mix": {**_mix(("new", 1)), "continuation": "borrow"}},
            {"daily_count": 1, "daily_mix": {**_mix(("new", 1)), "extra": 1}},
            {"daily_count": 7, "training_profile": "tokyo-interview-v1", "daily_mix": _mix(("new", 7))},
            {"run_time": "8:30"}, {"run_time": "24:00"}, {"run_time": "08:30:00"},
            {"timezone": "JST"}, {"timezone": "Mars/Base"},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(CoachError):
                validate_config(value)
        self.assertEqual(validate_config({"daily_count": 1, "daily_mix": _mix(("new", 1))})["daily_mix"]["continuation"], "dedicated")

    def test_backlog_keeps_the_new_slot(self) -> None:
        """Reserve the configured new slot while backlog stays pending.

        Inputs: Four unfinished attempts and a one-item new-only mix.
        Outputs: One new problem and four untouched backlog entries.
        Logic: Dedicated continuation never displaces another category.
        Dependencies: _select.
        """
        attempts = [_record(f"open-{n}", n, "2026-02-14", "D" if n % 2 else None) for n in range(1, 5)]
        snapshot = [dict(item) for item in attempts]
        chosen, diagnostics = self._select(attempts, _profile(1, _mix(("new", 1))))
        self.assertEqual(_categories(chosen), [("leetcode:5", "new")])
        self.assertEqual(len(diagnostics["unallocated_backlog"]), 4)
        self.assertEqual(attempts, snapshot)
        standard = validate_config({"daily_count": 1, "daily_mix": _mix(("new", 1))})
        chosen, diagnostics = self._select(attempts, standard)
        self.assertEqual([item["problem_id"] for item in chosen], ["leetcode:5"])
        self.assertEqual(len(diagnostics["unallocated_backlog"]), 4)

    def test_shortfall_is_reported_without_substitutes(self) -> None:
        """Report missing categories instead of filling them from another pool.

        Inputs: Unfinished, deferred, skipped, and unanswered work, but no weak evidence.
        Outputs: Weak and new shortfalls with reasons and no substitutes.
        Logic: Unfinished work is not weakness and retests are not new work.
        Dependencies: _select.
        """
        attempts = [_record("open", 1, "2026-02-14", None), _record("defer", 2, "2026-02-14", "E"),
                    _record("skip", 3, "2026-02-14", "F")]
        attempts += [_record(f"done-{n}", n, "2026-02-10", "A") for n in range(4, 8)]
        chosen, diagnostics = self._select(attempts, _profile(3, WEAK_NEW))
        self.assertEqual(chosen, [])
        missing = {item["category"]: item["missing"] for item in diagnostics["category_shortfalls"]}
        self.assertEqual(missing, {"weak": 2, "new": 1})
        self.assertEqual(diagnostics["categories"][1]["reasons"], {"no_eligible_candidates": 1})
        self.assertEqual(diagnostics["allocation"], [])

    def test_weak_waits_for_its_review_date(self) -> None:
        """Keep spacing rules for weak problems that are not yet due.

        Inputs: One assisted result recorded on the training date.
        Outputs: A weak shortfall with the next due date.
        Logic: Weak slots never retest early.
        Dependencies: _select.
        """
        chosen, diagnostics = self._select([_record("a1", 1, "2026-02-15", "C")], _profile(1, _mix(("weak", 1))))
        self.assertEqual(chosen, [])
        self.assertEqual(diagnostics["categories"][0]["next_due"], "2026-02-16")

    def test_one_problem_one_slot_and_other_language_is_not_new(self) -> None:
        """Count each problem once and exclude other-language practice from new work.

        Inputs: A weak due problem and Python practice on another problem.
        Outputs: Distinct problems, with the Python problem never labeled new.
        Logic: New means no recorded practice in any language.
        Dependencies: _select.
        """
        attempts = [_record("a1", 1, "2026-02-10", "C"), _record("py", 5, "2026-02-01", "A", language="Python")]
        mix = _mix(("weak", 1), ("review", 1), ("new", 4))
        chosen, _ = self._select(attempts, _profile(6, mix))
        ids = [item["problem_id"] for item in chosen]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("leetcode:5", ids)
        chosen, _ = self._select(attempts, validate_config({"daily_count": 6, "daily_mix": mix}))
        self.assertNotIn("leetcode:5", [item["problem_id"] for item in chosen])
        stored = {"candidates": self.context["candidates"], "practiced_problem_ids": ["leetcode:6"]}
        chosen, _ = select_with_diagnostics(self.catalog, [], _profile(1, _mix(("new", 1))), "2026-02-15", selection_context=stored)
        self.assertNotEqual(chosen[0]["problem_id"], "leetcode:6")

    def test_policy_cap_trims_from_the_last_slot(self) -> None:
        """Report policy-limited slots instead of exceeding a hard cap.

        Inputs: A three-item mix and a two-item policy cap.
        Outputs: Two items and a policy_cap_limited reason on the last category.
        Logic: Fill order is slot order; trimming starts from the end.
        Dependencies: _select and default_policy.
        """
        attempts = [_record("a1", 1, "2026-02-10", "C"), _record("a2", 2, "2026-02-11", "B")]
        policy = {**default_policy(), "max_daily_count": 2}
        chosen, diagnostics = self._select(attempts, _profile(3, WEAK_NEW), policy=policy)
        self.assertEqual(len(chosen), 2)
        self.assertEqual(diagnostics["category_shortfalls"][0]["category"], "new")
        self.assertEqual(diagnostics["category_shortfalls"][0]["reasons"]["policy_cap_limited"], 1)

    def test_sixth_slot_still_needs_a_reason(self) -> None:
        """Keep the interview profile's sixth-slot evidence rule.

        Inputs: A six-item new-only mix without a sixth justification.
        Outputs: Five items and a sixth_justification_missing reason.
        Logic: A configured mix does not relax evidence requirements.
        Dependencies: _select.
        """
        chosen, diagnostics = self._select([], _profile(6, _mix(("new", 6))))
        self.assertEqual(len(chosen), 5)
        self.assertIn("sixth_justification_missing", diagnostics["category_shortfalls"][0]["reasons"])


class DailyMixServiceTests(unittest.TestCase):
    """Verify configuration storage, previews, and frozen plans in temporary stores."""

    def setUp(self) -> None:
        """Create an isolated standard workspace.

        Inputs: None.
        Outputs: A temporary Coach.
        Logic: Use only synthetic settings and a private temporary path.
        Dependencies: tempfile and Coach.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "coach.sqlite3"
        self.coach = Coach(self.path)
        self.coach.initialize({"timezone": "UTC", "daily_count": 5})

    def tearDown(self) -> None:
        """Close the store and remove synthetic data.

        Inputs: The fixture.
        Outputs: None.
        Logic: Close SQLite before deleting files.
        Dependencies: Coach and tempfile.
        """
        self.coach.close()
        self.temp.cleanup()

    def _raw_config(self) -> str:
        """Read the stored configuration body directly.

        Inputs: None.
        Outputs: The canonical JSON text in SQLite.
        Logic: Inspect persistence without the service normalizer.
        Dependencies: sqlite3.
        """
        with sqlite3.connect(self.path) as connection:
            return connection.execute("SELECT body FROM config").fetchone()[0]

    def _counts(self) -> tuple:
        """Count rows that a preview must never write.

        Inputs: None.
        Outputs: Row counts for plans, attempts, config revision, and state version.
        Logic: Compare before and after read-only operations.
        Dependencies: sqlite3.
        """
        with sqlite3.connect(self.path) as connection:
            return tuple(connection.execute(sql).fetchone()[0] for sql in (
                "SELECT COUNT(*) FROM plans", "SELECT COUNT(*) FROM attempts",
                "SELECT revision FROM config", "SELECT version FROM learning_state"))

    def _update(self, changes: dict) -> dict:
        """Apply one configuration change at the current revision.

        Inputs: Configuration changes.
        Outputs: The saved configuration.
        Logic: Use the optimistic revision check.
        Dependencies: Coach.update_config.
        """
        return self.coach.update_config(changes, self.coach.get_config()["revision"])

    def test_null_mix_is_not_stored_and_can_be_restored(self) -> None:
        """Keep default stores unchanged and remove the field on restore.

        Inputs: A new store, then set and clear a mix.
        Outputs: No stored key by default or after restore.
        Logic: Older code can still read a restored store.
        Dependencies: _raw_config and _update.
        """
        self.assertNotIn("daily_mix", self._raw_config())
        self._update({"daily_count": 3, "daily_mix": WEAK_NEW})
        self.assertIn("daily_mix", self._raw_config())
        with self.assertRaises(CoachError):
            self._update({"daily_count": 4})
        self._update({"daily_mix": None, "daily_count": 5})
        self.assertNotIn("daily_mix", self._raw_config())
        self.assertNotIn("daily_mix", self.coach.get_config()["config"])

    def test_preview_writes_nothing(self) -> None:
        """Preview a mix without publishing a plan or allocating attempts.

        Inputs: A proposed mix and an unused date.
        Outputs: Mix diagnostics and unchanged row counts.
        Logic: Preview is read-only.
        Dependencies: Coach.preview_config and _counts.
        """
        before = self._counts()
        preview = self.coach.preview_config({"daily_count": 3, "daily_mix": WEAK_NEW}, "2026-01-01")
        self.assertFalse(preview["saved"])
        self.assertEqual(preview["daily_mix"]["category_shortfalls"][0]["category"], "weak")
        self.assertEqual(self._counts(), before)
        with self.assertRaises(CoachError):
            self.coach.preview_config({"daily_count": 4, "daily_mix": WEAK_NEW}, "2026-01-01")

    def test_backlog_mix_and_frozen_plan(self) -> None:
        """Allocate weak and new slots beside backlog and keep published plans.

        Inputs: Two assisted results, three unfinished attempts, and a mix.
        Outputs: Two weak retests and one new item; the plan is reused on rerun.
        Logic: Changed settings never rewrite an existing plan.
        Dependencies: Coach planning and feedback.
        """
        first = self.coach.ensure_plan("2026-01-01")
        for index, item in enumerate(first["items"]):
            result = "C" if index < 2 else "D"
            self.coach.submit_feedback(item["attempt_id"], f"mix-{index}", 0, {"result": result},
                                       occurred_at="2026-01-01T12:00:00+00:00")
        weak_ids = {item["problem"]["id"] for item in first["items"][:2]}
        self._update({"daily_count": 3, "daily_mix": WEAK_NEW})
        plan = self.coach.ensure_plan("2026-01-02")
        self.assertTrue(plan["created"])
        self.assertEqual({item["problem"]["id"] for item in plan["items"][:2]}, weak_ids)
        self.assertEqual(plan["items"][2]["attempt"]["feedback"], None)
        self.assertEqual(len(plan["diagnostics"]["daily_mix"]["unallocated_backlog"]), 3)
        for item in first["items"][2:]:
            self.assertEqual(self.coach.history(item["attempt_id"])["attempt"]["feedback"]["result"], "D")
        self._update({"daily_count": 1, "daily_mix": _mix(("new", 1))})
        again = self.coach.ensure_plan("2026-01-02")
        self.assertFalse(again["created"])
        self.assertEqual(again["id"], plan["id"])
        self.assertEqual(len(again["items"]), 3)

    def test_time_change_keeps_selection_and_state(self) -> None:
        """Change only run_time without touching selection or derived state.

        Inputs: A store with a mix, then a run_time change.
        Outputs: The same preview selection and the same state version.
        Logic: Scheduling fields are not learning rules.
        Dependencies: Coach configuration and preview.
        """
        self._update({"daily_count": 3, "daily_mix": WEAK_NEW})
        before = self.coach.preview_config({}, "2026-01-01")
        state = self._counts()[3]
        saved = self._update({"run_time": "09:00"})
        self.assertEqual(saved["config"]["daily_mix"]["slots"], WEAK_NEW["slots"])
        self.assertEqual(self._counts()[3], state)
        self.assertEqual(self.coach.preview_config({}, "2026-01-01")["selected"], before["selected"])

    def test_mix_change_keeps_schedule_fields(self) -> None:
        """Change only the mix without touching run_time or timezone.

        Inputs: A store with a run time, then a mix change.
        Outputs: Unchanged schedule fields.
        Logic: Each setting group can change alone.
        Dependencies: _update.
        """
        self._update({"run_time": "08:30", "timezone": "Asia/Tokyo"})
        saved = self._update({"daily_count": 3, "daily_mix": WEAK_NEW})["config"]
        self.assertEqual((saved["run_time"], saved["timezone"]), ("08:30", "Asia/Tokyo"))

    def test_interview_target_follows_a_smaller_daily_count(self) -> None:
        """Report the interview target from daily_count instead of a fixed five.

        Inputs: An interview workspace with daily_count three and no research.
        Outputs: A target of three and a shortfall of three.
        Logic: The profile targets five only when capacity allows it.
        Dependencies: Coach.preview_config.
        """
        self.coach.close()
        path = Path(self.temp.name) / "profile" / "coach.sqlite3"
        coach = Coach(path)
        try:
            coach.initialize({"timezone": "Asia/Tokyo", "daily_count": 3, "training_profile": "tokyo-interview-v1"})
            report = coach.preview_config({}, "2026-01-05")
            self.assertEqual(report["target_count"], 3)
            self.assertEqual(report["shortfall"], 3 - report["selected_count"])
            report = coach.preview_config({"daily_count": 6}, "2026-01-05")
            self.assertEqual(report["target_count"], 5)
        finally:
            coach.close()


if __name__ == "__main__":
    unittest.main()
