"""Validate feedback and derive deterministic training decisions without a model.

All outcomes describe user reports. These rules do not verify accepted solutions.
"""

from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
import math
import re
from typing import NoReturn
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .catalog import PROBLEMS
from ..errors import CoachError
from .policies import default_policy, filter_catalog, policy_active, validate_plan_candidates, validate_policy

RULE_VERSION = "1"
FEEDBACK_FIELDS = (
    "result", "elapsed_minutes", "blocked_on", "explanation", "boundary_tests",
    "proficiency", "time_complexity", "space_complexity", "defer_until",
    "skip_until", "assistance", "hint_level", "error_types",
    "closed_book_minutes", "reading_minutes", "can_explain_invariant",
    "can_explain_correctness", "can_explain_complexity",
)
COMPLETED_RESULTS = {"A", "B", "C"}
ABILITY_RESULTS = {"A", "B", "C", "D"}
# Optional settings are omitted from stored bodies while they keep their default.
OPTIONAL_CONFIG = {"daily_mix": None}
MIX_CATEGORIES = ("continue", "weak", "review", "new")
MIX_CONTINUATION = ("dedicated", "fill_unused")
PROFILE_DAILY_CEILING = 6
# Changing these fields does not change derived learning evidence.
NON_LEARNING_FIELDS = {"run_time", "daily_mix"}


def _fail(message: str) -> NoReturn:
    """Raise a shared validation error.

    Inputs: A short error message.
    Outputs: No return value; raises CoachError.
    Logic: Use one stable error code for invalid rule inputs.
    Dependencies: CoachError.
    """
    raise CoachError("validation_error", message)


def _date(value: object, field: str) -> date:
    """Parse a strict calendar date.

    Inputs: A YYYY-MM-DD value and its field name.
    Outputs: A date object, or a validation error.
    Logic: Check the text format before calendar parsing.
    Dependencies: datetime.date and re.
    """
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        _fail(f"{field} must use YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        _fail(f"{field} is not a valid calendar date.")


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    """Validate a bounded integer without accepting booleans.

    Inputs: A value, field name, and inclusive limits.
    Outputs: The integer value, or a validation error.
    Logic: Reject bool even though Python treats it as an integer.
    Dependencies: _fail for validation errors.
    """
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(f"{field} must be an integer from {minimum} to {maximum}.")
    return value


def _plus_days(day: date, days: int) -> date:
    """Add a configured interval within the supported calendar range.

    Inputs: A calendar date and a positive day interval.
    Outputs: The later date, or a validation error.
    Logic: Reject a date overflow before it can escape a feedback transaction.
    Dependencies: datetime.timedelta and CoachError.
    """
    try:
        return day + timedelta(days=days)
    except OverflowError:
        _fail("The practice date and review interval exceed the calendar range.")


def default_config() -> dict:
    """Return independent default settings for one learner.

    Inputs: None.
    Outputs: A new configuration dictionary.
    Logic: Keep the initial plan small and require explicit scheduling setup.
    Dependencies: None.
    """
    return {
        "language": "Java", "daily_count": 5, "baseline_count": 4,
        "timezone": "UTC", "run_time": None, "review_intervals": [3, 7],
        "assisted_review_days": 1, "stable_review_days": 30,
        "skip_cooldown_days": 7, "training_profile": "standard",
    }


def validate_config(config: dict) -> dict:
    """Normalize supported training settings.

    Inputs: A dictionary with supported configuration fields.
    Outputs: A complete, independent configuration dictionary.
    Logic: Merge defaults, then validate types, timezone, and intervals.
    Dependencies: default_config, zoneinfo, and validation helpers.
    """
    if not isinstance(config, dict):
        _fail("Configuration must be an object.")
    if not all(isinstance(key, str) for key in config):
        _fail("Configuration field names must be strings.")
    result = default_config()
    unknown = set(config) - set(result) - set(OPTIONAL_CONFIG)
    if unknown:
        _fail(f"Unsupported configuration fields: {', '.join(sorted(unknown))}.")
    result.update(deepcopy(config))
    if not isinstance(result["training_profile"], str) or result["training_profile"] not in {"standard", "tokyo-interview-v1"}:
        _fail("training_profile must be standard or tokyo-interview-v1.")
    language = result["language"]
    if not isinstance(language, str) or not language.strip() or len(language) > 40:
        _fail("language must be a non-empty string of at most 40 characters.")
    result["language"] = language.strip()
    for key, minimum, maximum in (
        ("daily_count", 1, 100), ("baseline_count", 0, 100),
        ("assisted_review_days", 1, 365), ("stable_review_days", 1, 3650),
        ("skip_cooldown_days", 1, 3650),
    ):
        _integer(result[key], key, minimum, maximum)
    timezone = result["timezone"]
    if not isinstance(timezone, str) or len(timezone) > 100:
        _fail("timezone must be an IANA timezone name.")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        _fail("timezone must be an available IANA timezone name.")
    run_time = result["run_time"]
    if run_time is not None and (
        not isinstance(run_time, str)
        or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", run_time)
    ):
        _fail("run_time must use HH:MM, or be null.")
    intervals = result["review_intervals"]
    if not isinstance(intervals, list) or not 1 <= len(intervals) <= 10:
        _fail("review_intervals must contain 1 to 10 day intervals.")
    for interval in intervals:
        _integer(interval, "review_intervals entry", 1, 3650)
    mix = validate_daily_mix(result.pop("daily_mix", None), result)
    if mix is not None:
        result["daily_mix"] = mix
    return result


def validate_daily_mix(mix: object, settings: dict) -> dict | None:
    """Normalize an optional per-category daily allocation.

    Inputs: A daily_mix value and otherwise validated settings.
    Outputs: A normalized mix object, or None for the original selection rules.
    Logic: Require known unique categories whose counts sum to daily_count.
    Dependencies: MIX_CATEGORIES, MIX_CONTINUATION, and validation helpers.
    """
    if mix is None:
        return None
    if not isinstance(mix, dict) or not all(isinstance(key, str) for key in mix):
        _fail("daily_mix must be an object or null.")
    unknown = set(mix) - {"slots", "continuation"}
    if unknown:
        _fail(f"Unsupported daily_mix fields: {', '.join(sorted(unknown))}.")
    continuation = mix.get("continuation", "dedicated")
    if continuation not in MIX_CONTINUATION:
        _fail("daily_mix continuation must be dedicated or fill_unused.")
    slots = mix.get("slots")
    if not isinstance(slots, list) or not 1 <= len(slots) <= len(MIX_CATEGORIES):
        _fail(f"daily_mix slots must list 1 to {len(MIX_CATEGORIES)} categories.")
    profile = settings["training_profile"] == "tokyo-interview-v1"
    ceiling = PROFILE_DAILY_CEILING if profile else 100
    normalized, seen = [], set()
    for slot in slots:
        if not isinstance(slot, dict) or set(slot) != {"category", "count"}:
            _fail("Each daily_mix slot needs only category and count.")
        category = slot["category"]
        if not isinstance(category, str) or category not in MIX_CATEGORIES:
            _fail(f"daily_mix category must be one of: {', '.join(MIX_CATEGORIES)}.")
        if category in seen:
            _fail("daily_mix categories must not repeat.")
        seen.add(category)
        _integer(slot["count"], f"daily_mix {category} count", 0, ceiling)
        normalized.append({"category": category, "count": slot["count"]})
    total = sum(slot["count"] for slot in normalized)
    if total != settings["daily_count"]:
        _fail(f"daily_mix counts sum to {total}; they must equal daily_count {settings['daily_count']}.")
    if profile and total > PROFILE_DAILY_CEILING:
        _fail(f"The interview profile allows at most {PROFILE_DAILY_CEILING} daily items.")
    return {"slots": normalized, "continuation": continuation}


def merge_feedback(previous: dict | None, changes: dict, kind: str = "progress") -> dict:
    """Apply validated partial feedback to one practice attempt.

    Inputs: A prior snapshot, changed fields, and progress or correction.
    Outputs: A complete feedback snapshot with explicit unanswered fields.
    Logic: Preserve omitted fields. Keep prior assistance during progress.
    Dependencies: FEEDBACK_FIELDS and validation helpers.
    """
    if not isinstance(kind, str) or kind not in {"progress", "correction"}:
        _fail("kind must be progress or correction.")
    if not isinstance(changes, dict):
        _fail("Feedback changes must be an object.")
    if not all(isinstance(key, str) for key in changes):
        _fail("Feedback field names must be strings.")
    unknown = set(changes) - set(FEEDBACK_FIELDS)
    if unknown:
        _fail(f"Unsupported feedback fields: {', '.join(sorted(unknown))}.")
    snapshot = dict.fromkeys(FEEDBACK_FIELDS)
    if previous is not None:
        snapshot.update(previous)
    snapshot.update(deepcopy(changes))
    result = snapshot["result"]
    if result is not None and (not isinstance(result, str) or result not in "ABCDEF" or len(result) != 1):
        _fail("result must be A, B, C, D, E, F, or null.")
    minutes = snapshot["elapsed_minutes"]
    if minutes is not None:
        if type(minutes) not in {int, float} or minutes < 0:
            _fail("elapsed_minutes must be a finite non-negative number, or null.")
        try:
            finite = math.isfinite(minutes)
        except OverflowError:
            finite = False
        if not finite:
            _fail("elapsed_minutes must be a finite non-negative number, or null.")
    for key in ("blocked_on", "time_complexity", "space_complexity"):
        value = snapshot[key]
        if value is not None:
            if not isinstance(value, str) or len(value) > 4000:
                _fail(f"{key} must be a string of at most 4000 characters, or null.")
            snapshot[key] = value.strip()
    for key in ("closed_book_minutes", "reading_minutes"):
        value = snapshot[key]
        if value is not None:
            if type(value) not in (int, float) or value < 0:
                _fail(f"{key} must be finite non-negative minutes, or null.")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                _fail(f"{key} must be finite non-negative minutes, or null.")
    for key in ("can_explain_invariant", "can_explain_correctness", "can_explain_complexity"):
        if snapshot[key] is not None and type(snapshot[key]) is not bool:
            _fail(f"{key} must be true, false, or null.")
    if snapshot["hint_level"] is not None and snapshot["hint_level"] not in ("none", "minor", "key", "solution"):
        _fail("hint_level must be none, minor, key, solution, or null.")
    errors = snapshot["error_types"]
    if errors is not None and (not isinstance(errors, list) or len(errors) > 50 or any(not isinstance(item, str) or not item.strip() or len(item) > 4000 for item in errors)):
        _fail("error_types must contain at most 50 non-empty labels, or null.")
    explanation = snapshot["explanation"]
    if explanation is not None and (
        not isinstance(explanation, str)
        or explanation not in {"not_tried", "partial", "clear", "uncertain"}
    ):
        _fail("explanation must be not_tried, partial, clear, uncertain, or null.")
    if snapshot["boundary_tests"] is not None and type(snapshot["boundary_tests"]) is not bool:
        _fail("boundary_tests must be true, false, or null.")
    if snapshot["proficiency"] is not None:
        _integer(snapshot["proficiency"], "proficiency", 1, 5)
    for key in ("defer_until", "skip_until"):
        if snapshot[key] is not None:
            _date(snapshot[key], key)
    assistance = snapshot["assistance"]
    if assistance is not None and (
        not isinstance(assistance, str) or assistance not in {"none", "hint", "solution"}
    ):
        _fail("assistance must be none, hint, solution, or null.")
    hint_assistance = {"none": "none", "minor": "hint", "key": "hint", "solution": "solution"}.get(snapshot["hint_level"])
    if hint_assistance is not None:
        if assistance is None:
            snapshot["assistance"] = assistance = hint_assistance
        elif assistance != hint_assistance:
            _fail("The hint level conflicts with reported assistance.")
    required_assistance = {"A": "none", "B": "hint", "C": "solution"}.get(result)
    if required_assistance is not None:
        if "result" in changes and "assistance" not in changes:
            rank = {None: 0, "none": 0, "hint": 1, "solution": 2}
            if kind == "progress" and rank[assistance] > rank[required_assistance]:
                _fail("Progress cannot erase assistance. Use a correction for a wrong report.")
            snapshot["assistance"] = required_assistance
        elif assistance is None:
            snapshot["assistance"] = required_assistance
        elif assistance != required_assistance:
            _fail("The result conflicts with reported assistance. Use B or C when needed.")
    if kind == "progress" and previous:
        rank = {None: 0, "none": 0, "hint": 1, "solution": 2}
        if rank[snapshot["assistance"]] < rank[previous.get("assistance")]:
            _fail("Progress cannot erase assistance. Use a correction for a wrong report.")
        if previous.get("result") in COMPLETED_RESULTS and result not in COMPLETED_RESULTS:
            _fail("Use a correction to change a completed result to an unfinished result.")
        old_minutes = previous.get("elapsed_minutes")
        if old_minutes is not None and (minutes is None or minutes < old_minutes):
            _fail("Use a correction to reduce or clear cumulative elapsed time.")
    return snapshot


def _attempt_order(attempt: dict) -> tuple:
    """Build a stable chronological key for an attempt snapshot.

    Inputs: An attempt with practice and planned dates.
    Outputs: A tuple suitable for sorting.
    Logic: Use practice date, event time, creation time, then the unique ID.
    Dependencies: None.
    """
    return (
        attempt.get("practice_date") or attempt.get("planned_date") or attempt.get("created_on"),
        attempt.get("occurred_at") or "", attempt.get("created_at") or "", attempt["id"],
    )


def derive_learning_state(attempts: list[dict], config: dict, catalog: list[dict] | None = None) -> dict:
    """Rebuild learning evidence and review dates from effective feedback.

    Inputs: Attempt snapshots, settings, and optional stored catalog metadata.
    Outputs: Problem states, topic evidence, and the rule version.
    Logic: Count each attempt once. Require spaced independent reports for mastery.
    Dependencies: Catalog tags, date arithmetic, and configured review intervals.
    """
    return _derive_state(attempts, validate_config(config), PROBLEMS if catalog is None else catalog)


def _derive_state(attempts: list[dict], settings: dict, catalog: list[dict]) -> dict:
    """Derive state after the public entry validated configuration.

    Inputs: Current attempts, normalized settings, and catalog metadata.
    Outputs: The configured learning projection.
    Logic: Share one trusted calculation between planning and direct derivation.
    Dependencies: Profile rules and standard spacing logic.
    """
    if settings["training_profile"] == "tokyo-interview-v1":
        from .training_profile import derive_profile_state

        return derive_profile_state(attempts, settings, catalog)
    if any(attempt["learning_checkpoint"]["evidence_coverage"] != "complete"
           for attempt in attempts if "learning_checkpoint" in attempt):
        raise CoachError("checkpoint_profile_unsupported", "The standard profile requires complete replay evidence.")
    groups = defaultdict(list)
    catalog_by_id = {problem["id"]: problem for problem in catalog}
    for attempt in attempts:
        groups[(attempt["problem_id"], attempt["language"])].append(attempt)
    problems = []
    topics = {}
    for (problem_id, language), records in sorted(groups.items()):
        records = sorted(records, key=_attempt_order)
        ability = []
        for attempt in records:
            feedback = attempt.get("feedback") or {}
            if feedback.get("result") in ABILITY_RESULTS:
                ability.append(attempt)
        completed = [item for item in ability if item["feedback"]["result"] in COMPLETED_RESULTS]
        independent = [item for item in ability if item["feedback"]["result"] == "A"]
        latest = ability[-1] if ability else None
        weakness = 0
        for item in ability[-5:]:
            weakness += {"A": -1, "B": 1, "C": 2, "D": 3}[item["feedback"]["result"]]
        weakness = max(0, weakness)
        mastery = "unseen" if not ability else "learning"
        review_due = None
        review_source = None
        qualifying_dates = []
        for item in ability:
            if item["feedback"]["result"] != "A":
                qualifying_dates = []
                continue
            practice_day = _date(_attempt_order(item)[0], "practice_date")
            if not qualifying_dates:
                qualifying_dates.append(practice_day)
            elif len(qualifying_dates) <= len(settings["review_intervals"]):
                gap = settings["review_intervals"][len(qualifying_dates) - 1]
                if (practice_day - qualifying_dates[-1]).days >= gap:
                    qualifying_dates.append(practice_day)
        if latest is not None:
            result = latest["feedback"]["result"]
            latest_day = _date(_attempt_order(latest)[0], "practice_date")
            if result in {"B", "C"}:
                review_due = _plus_days(latest_day, settings["assisted_review_days"]).isoformat()
                review_source = latest["id"]
            elif result == "A":
                mastery = "independent"
                if len(qualifying_dates) > len(settings["review_intervals"]):
                    mastery = "stable"
                    review_day = _plus_days(latest_day, settings["stable_review_days"])
                else:
                    next_gap = settings["review_intervals"][len(qualifying_dates) - 1]
                    review_day = _plus_days(qualifying_dates[-1], next_gap)
                review_due = review_day.isoformat()
                review_source = latest["id"]
        evidence = [item["id"] for item in ability]
        state = {
            "problem_id": problem_id, "language": language,
            "completed_count": len(completed), "independent_count": len(independent),
            "mastery_status": mastery, "weakness_score": weakness,
            "review_due": review_due, "review_source_attempt_id": review_source,
            "evidence": evidence, "last_result": latest["feedback"]["result"] if latest else None,
            "last_practice_date": _attempt_order(latest)[0] if latest else None,
        }
        problems.append(state)
        for tag in catalog_by_id.get(problem_id, {}).get("tags", []):
            topic = topics.setdefault((tag, language), {"tag": tag, "language": language, "weakness_score": 0, "evidence": []})
            topic["weakness_score"] += weakness
            if weakness:
                topic["evidence"].extend(evidence)
    return {
        "problems": problems, "topics": [topics[key] for key in sorted(topics)],
        "rule_version": RULE_VERSION, "basis": "self_reported",
    }


def select_with_diagnostics(
    catalog: list[dict], attempts: list[dict], config: dict,
    training_date: str, state: dict | None = None, policy: dict | None = None,
    selection_context: dict | None = None,
) -> tuple[list[dict], dict | None]:
    """Select daily candidates and return configured-mix diagnostics.

    Inputs: The same values as select_candidates.
    Outputs: Candidates and mix diagnostics, or None without a daily_mix.
    Logic: Use the original selectors unless the learner configured a mix.
    Dependencies: select_candidates and daily_mix.select_mixed.
    """
    settings = validate_config(config)
    if settings.get("daily_mix") is None:
        return select_candidates(catalog, attempts, settings, training_date, state, policy, selection_context), None
    active_policy = validate_policy(default_policy() if policy is None else policy, catalog)
    if not policy_active(active_policy, training_date):
        raise CoachError("inactive_policy", "The selected policy does not cover the training date.")
    _date(training_date, "training_date")
    state = state if state is not None else _derive_state(attempts, settings, catalog)
    from .daily_mix import select_mixed

    result = select_mixed(catalog, attempts, settings, training_date, state, active_policy, selection_context)
    return result["selected"], result["diagnostics"]


def select_candidates(
    catalog: list[dict], attempts: list[dict], config: dict,
    training_date: str, state: dict | None = None, policy: dict | None = None,
    selection_context: dict | None = None,
) -> list[dict]:
    """Fill a bounded plan with continuation, reviews, and useful new work.

    Inputs: Catalog, attempts, settings, date, optional state, and resolved policy.
    Outputs: Ordered candidate dictionaries with existing or new attempt links.
    Logic: Gate every selection by hard scope. Rank eligible continuation first.
    Dependencies: Derived state, policy checks, calendar arithmetic, and metadata.
    """
    settings = validate_config(config)
    today = _date(training_date, "training_date")
    active_policy = validate_policy(default_policy() if policy is None else policy, catalog)
    if not policy_active(active_policy, training_date):
        raise CoachError("inactive_policy", "The selected policy does not cover the training date.")
    eligible_catalog = filter_catalog(catalog, active_policy)
    state = state if state is not None else _derive_state(attempts, settings, catalog)
    if settings.get("daily_mix") is not None:
        from .daily_mix import select_mixed

        return select_mixed(catalog, attempts, settings, training_date, state, active_policy, selection_context)["selected"]
    if settings["training_profile"] == "tokyo-interview-v1":
        from .training_profile import select_profile_candidates

        return select_profile_candidates(catalog, attempts, settings, training_date, state, active_policy, selection_context)
    language = settings["language"]
    maximum = active_policy["max_daily_count"]
    capacity = min(settings["daily_count"], maximum) if maximum is not None else settings["daily_count"]
    by_problem = {problem["id"]: problem for problem in eligible_catalog}
    records = [attempt for attempt in attempts if attempt["language"] == language]
    grouped = defaultdict(list)
    for attempt in sorted(records, key=_attempt_order):
        grouped[attempt["problem_id"]].append(attempt)
    selected = []
    selected_ids = set()
    parked = set()
    pending = []
    for problem_id, history in grouped.items():
        if problem_id not in by_problem:
            continue
        for attempt in history:
            planned = attempt.get("planned_date") or attempt.get("created_on")
            if planned and _date(planned, "planned_date") > today:
                parked.add(problem_id)
                continue
            feedback = attempt.get("feedback") or {}
            result = feedback.get("result")
            if result is None or result == "D":
                priority = 0 if result == "D" else 1
                pending.append((priority, planned or _attempt_order(attempt)[0], attempt.get("created_at") or "", attempt["id"], attempt))
            elif result == "E":
                deferred = feedback.get("defer_until")
                if deferred is not None and _date(deferred, "defer_until") <= today:
                    pending.append((0, planned or _attempt_order(attempt)[0], attempt.get("created_at") or "", attempt["id"], attempt))
                else:
                    parked.add(problem_id)
        latest = history[-1]
        feedback = latest.get("feedback") or {}
        if feedback.get("result") == "F":
            until = feedback.get("skip_until")
            if until is None:
                until_day = _plus_days(_date(_attempt_order(latest)[0], "practice_date"), settings["skip_cooldown_days"])
            else:
                until_day = _date(until, "skip_until")
            if today < until_day:
                parked.add(problem_id)
    for _, _, _, _, attempt in sorted(pending):
        problem_id = attempt["problem_id"]
        if len(selected) >= capacity:
            break
        if problem_id in selected_ids:
            continue
        selected.append({"problem_id": problem_id, "attempt_id": attempt["id"], "reason": "continue", "review_source_attempt_id": None})
        selected_ids.add(problem_id)
    problem_states = {}
    due_reviews = []
    for problem in state["problems"]:
        if problem["language"] != language:
            continue
        problem_id = problem["problem_id"]
        problem_states[problem_id] = problem
        if problem["review_due"] is not None and problem["review_due"] <= training_date:
            due_reviews.append((problem["review_due"], problem_id, problem))
    for _, problem_id, problem in sorted(due_reviews):
        if len(selected) >= capacity:
            break
        if problem_id not in by_problem or problem_id in selected_ids or problem_id in parked:
            continue
        selected.append({"problem_id": problem_id, "attempt_id": None, "reason": "retest", "review_source_attempt_id": problem["review_source_attempt_id"]})
        selected_ids.add(problem_id)
    topic_scores = {item["tag"]: item["weakness_score"] for item in state["topics"] if item["language"] == language}
    candidates = []
    for problem in eligible_catalog:
        problem_id = problem["id"]
        if problem_id in selected_ids or problem_id in parked:
            continue
        if problem_states.get(problem_id, {}).get("completed_count", 0):
            continue
        if any((item.get("feedback") or {}).get("result") in {None, "D", "E"} for item in grouped.get(problem_id, [])):
            continue
        candidates.append(problem)
    covered_tags = set()
    for item in selected:
        covered_tags.update(by_problem[item["problem_id"]]["tags"])
    while candidates and len(selected) < capacity:
        scored = []
        base_slot = len(selected) < min(settings["baseline_count"], capacity)
        for problem in candidates:
            weak_score = sum(topic_scores.get(tag, 0) for tag in problem["tags"])
            preferred_score = len(set(problem["tags"]).intersection(active_policy["preferred_topics"]))
            desired_difficulty = "easy" if base_slot else "medium"
            difficulty_cost = int(problem["difficulty"] != desired_difficulty)
            overlap = len(covered_tags.intersection(problem["tags"]))
            scored.append((-weak_score, -preferred_score, difficulty_cost, overlap, int(problem["id"].split(":")[-1]), problem["id"], problem))
        best = min(scored)
        problem = best[-1]
        if best[0] < 0:
            reason = "weakness"
        elif best[1] < 0:
            reason = "preferred_topic"
        else:
            reason = "foundation" if base_slot else "representative"
        selected.append({"problem_id": problem["id"], "attempt_id": None, "reason": reason, "review_source_attempt_id": None})
        selected_ids.add(problem["id"])
        covered_tags.update(problem["tags"])
        candidates.remove(problem)
    validate_plan_candidates(selected, catalog, active_policy, settings)
    return selected
