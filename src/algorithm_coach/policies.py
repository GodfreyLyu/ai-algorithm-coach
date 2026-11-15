"""Define bounded training scopes and deterministic policy safety checks."""

from copy import deepcopy
from datetime import date
import re

from .catalog_validation import DIFFICULTIES
from .errors import CoachError


def default_policy() -> dict:
    """Return the unrestricted baseline policy.

    Inputs: None.
    Outputs: An independent policy object with explicit defaults.
    Logic: Keep scope unrestricted until the learner activates a policy.
    Dependencies: None.
    """
    return {
        "name": "Default training scope", "topics_any": None,
        "difficulties": None, "problem_ids": None, "excluded_problem_ids": [],
        "preferred_topics": [], "max_daily_count": None,
        "effective_from": "0001-01-01", "effective_until": None,
    }


def _calendar_date(value: object, field: str) -> date:
    """Read a strict policy boundary date.

    Inputs: A proposed date and its field name.
    Outputs: A parsed date, or a validation error.
    Logic: Require an exact ISO date and a valid calendar day.
    Dependencies: datetime.date, re, and CoachError.
    """
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise CoachError("validation_error", f"{field} must use YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CoachError("validation_error", f"{field} is not a valid calendar date.") from exc


def _known_list(value: object, field: str, known: set, allow_null: bool, allow_empty: bool) -> list[str] | None:
    """Normalize one finite policy list against known metadata.

    Inputs: A list value, field name, known values, and null or empty permissions.
    Outputs: A sorted list, null, or a validation error.
    Logic: Reject unknown values and duplicates rather than broadening scope.
    Dependencies: CoachError.
    """
    if value is None:
        if allow_null:
            return None
        raise CoachError("validation_error", f"{field} must be a list, not null.")
    if not isinstance(value, list) or len(value) > 10000:
        raise CoachError("validation_error", f"{field} must be a list with at most 10000 entries.")
    if not value and not allow_empty:
        raise CoachError("validation_error", f"{field} cannot be empty. Use null for unrestricted scope.")
    values = set()
    for item in value:
        if not isinstance(item, str) or item not in known:
            raise CoachError("validation_error", f"{field} contains an unknown value.")
        if item in values:
            raise CoachError("validation_error", f"{field} must not contain duplicates.")
        values.add(item)
    return sorted(values)


def validate_policy(body: dict, catalog: list[dict]) -> dict:
    """Normalize one declarative policy against the current catalog.

    Inputs: Policy fields and validated catalog metadata.
    Outputs: A complete policy containing only supported fields.
    Logic: Intersect allow filters. Keep exclusions separate so deny wins.
    Dependencies: default_policy, metadata labels, and validation helpers.
    """
    if not isinstance(body, dict) or not all(isinstance(key, str) for key in body):
        raise CoachError("validation_error", "Policy fields must form an object with string keys.")
    normalized = default_policy()
    unknown = set(body) - set(normalized)
    if unknown:
        raise CoachError("validation_error", f"Unsupported policy fields: {', '.join(sorted(unknown))}.")
    normalized.update(deepcopy(body))
    name = normalized["name"]
    if not isinstance(name, str) or not name.strip() or len(name) > 100 or not name.isprintable():
        raise CoachError("validation_error", "Policy name must be printable text from 1 to 100 characters.")
    normalized["name"] = name.strip()
    known_ids = {problem["id"] for problem in catalog}
    known_topics = {tag for problem in catalog for tag in problem["tags"]}
    for field, known, allow_null, allow_empty in (
        ("topics_any", known_topics, True, False),
        ("difficulties", set(DIFFICULTIES), True, False),
        ("problem_ids", known_ids, True, False),
        ("excluded_problem_ids", known_ids, False, True),
        ("preferred_topics", known_topics, False, True),
    ):
        normalized[field] = _known_list(normalized[field], field, known, allow_null, allow_empty)
    maximum = normalized["max_daily_count"]
    if maximum is not None and (type(maximum) is not int or not 1 <= maximum <= 100):
        raise CoachError("validation_error", "max_daily_count must be an integer from 1 to 100, or null.")
    starts = _calendar_date(normalized["effective_from"], "effective_from")
    if normalized["effective_until"] is not None:
        ends = _calendar_date(normalized["effective_until"], "effective_until")
        if ends < starts:
            raise CoachError("validation_error", "effective_until cannot precede effective_from.")
    return normalized


def policy_active(policy: dict, training_date: str) -> bool:
    """Check whether a normalized policy covers a training day.

    Inputs: A normalized policy and a strict ISO training date.
    Outputs: True when both inclusive date boundaries match.
    Logic: Evaluate the bounded phase without mutating policy history.
    Dependencies: _calendar_date.
    """
    day = _calendar_date(training_date, "training_date")
    starts = _calendar_date(policy["effective_from"], "effective_from")
    ends = policy["effective_until"]
    return day >= starts and (ends is None or day <= _calendar_date(ends, "effective_until"))


def eligibility(problem: dict, policy: dict) -> dict:
    """Explain whether one problem passes all hard scope limits.

    Inputs: Validated problem metadata and a normalized policy.
    Outputs: An allowed flag and stable reason codes for denied rules.
    Logic: Combine allow filters with AND. Exclusions always deny selection.
    Dependencies: Policy keys and problem metadata; no model or storage access.
    """
    reasons = []
    if problem["id"] in policy["excluded_problem_ids"]:
        reasons.append("excluded_problem_id")
    if policy["problem_ids"] is not None and problem["id"] not in policy["problem_ids"]:
        reasons.append("problem_id_not_allowed")
    if policy["topics_any"] is not None and not set(problem["tags"]).intersection(policy["topics_any"]):
        reasons.append("topic_not_allowed")
    if policy["difficulties"] is not None and problem["difficulty"] not in policy["difficulties"]:
        reasons.append("difficulty_not_allowed")
    return {"allowed": not reasons, "reasons": reasons}


def filter_catalog(catalog: list[dict], policy: dict) -> list[dict]:
    """Keep catalog entries that pass the normalized policy.

    Inputs: Validated catalog metadata and a normalized policy.
    Outputs: An eligible list in the original catalog order.
    Logic: Apply the same eligibility predicate used by post-validation.
    Dependencies: eligibility.
    """
    return [problem for problem in catalog if eligibility(problem, policy)["allowed"]]


def validate_plan_candidates(candidates: list[dict], catalog: list[dict], policy: dict, config: dict) -> None:
    """Reject a generated plan that violates hard scope or daily capacity.

    Inputs: Candidate records, full catalog, normalized policy, and settings.
    Outputs: None on success; otherwise a structured policy error.
    Logic: Recheck known IDs, exclusions, uniqueness, and the tighter count limit.
    Dependencies: eligibility and CoachError; no model output is trusted.
    """
    if not isinstance(candidates, list):
        raise CoachError("policy_violation", "Plan candidates must be a list.")
    daily_count = config.get("daily_count")
    if type(daily_count) is not int or not 1 <= daily_count <= 100:
        raise CoachError("validation_error", "daily_count must be an integer from 1 to 100.")
    normalized = validate_policy(policy, catalog)
    maximum = normalized["max_daily_count"]
    capacity = min(daily_count, maximum) if maximum is not None else daily_count
    if len(candidates) > capacity:
        raise CoachError("policy_violation", "Plan candidates exceed daily capacity.", {"capacity": capacity})
    known = {problem["id"]: problem for problem in catalog}
    seen = set()
    seen_attempts = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("problem_id"), str):
            raise CoachError("policy_violation", "Every plan candidate needs a known problem ID.")
        problem_id = candidate["problem_id"]
        if problem_id not in known:
            raise CoachError("policy_violation", "A plan candidate refers to an unknown problem ID.")
        if problem_id in seen:
            raise CoachError("policy_violation", "Plan candidates must not repeat a problem ID.")
        seen.add(problem_id)
        attempt_id = candidate.get("attempt_id")
        if attempt_id is not None:
            if not isinstance(attempt_id, str) or not attempt_id or attempt_id in seen_attempts:
                raise CoachError("policy_violation", "Plan candidates must use distinct valid attempt IDs.")
            seen_attempts.add(attempt_id)
        decision = eligibility(known[problem_id], normalized)
        if not decision["allowed"]:
            raise CoachError("policy_violation", "A plan candidate falls outside the active scope.", {"problem_id": problem_id, "reasons": decision["reasons"]})
