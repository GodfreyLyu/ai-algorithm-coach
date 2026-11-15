"""Derive topic completion rates from current self-reported practice evidence."""

from collections import defaultdict

from .errors import CoachError

SCORE_VERSION = "1"
VALID_RESULTS = ("A", "B", "C", "D")


def _practice_order(attempt: dict) -> tuple:
    """Build an evidence-time key without using correction receipt time.

    Inputs: One effective attempt with canonical dates and timestamps.
    Outputs: A stable chronological tuple.
    Logic: Compare practice date, occurrence time, creation time, then ID.
    Dependencies: The core attempt snapshot contract; no clock or storage calls.
    """
    return (
        attempt.get("practice_date") or attempt.get("planned_date") or attempt.get("created_on") or "",
        attempt.get("occurred_at") or "", attempt.get("created_at") or "",
        attempt["id"],
    )


def derive_topic_scores(attempts: list[dict], catalog: list[dict], language: str, problem_states: list[dict]) -> dict:
    """Compute per-topic independent completion rates from distinct problems.

    Inputs: Effective attempts, stored catalog, language, and existing problem states.
    Outputs: Topic scores, result counts, sample flags, and explicit score provenance.
    Logic: Use the newest A-D attempt per problem. Round half up using integers.
    Dependencies: Catalog tags and existing mastery states; no writes or new mastery rules.
    """
    if not isinstance(language, str) or not language.strip() or len(language) > 40:
        raise CoachError("validation_error", "language must be non-empty text of at most 40 characters.")
    selected_language = language.strip()
    known = {problem["id"]: problem for problem in catalog}
    latest = {}
    for attempt in attempts:
        feedback = attempt.get("feedback") or {}
        problem_id = attempt["problem_id"]
        if attempt["language"] != selected_language or problem_id not in known:
            continue
        if feedback.get("result") not in VALID_RESULTS:
            continue
        previous = latest.get(problem_id)
        if previous is None or _practice_order(attempt) > _practice_order(previous):
            latest[problem_id] = attempt
    stable_problems = {
        state["problem_id"] for state in problem_states
        if state["language"] == selected_language and state.get("mastery_status") == "stable"
    }
    topic_problems = defaultdict(set)
    for problem in catalog:
        for tag in set(problem["tags"]):
            topic_problems[tag].add(problem["id"])
    topics = []
    for tag in sorted(topic_problems):
        evidence_ids = topic_problems[tag].intersection(latest)
        results = dict.fromkeys(VALID_RESULTS, 0)
        for problem_id in evidence_ids:
            results[latest[problem_id]["feedback"]["result"]] += 1
        problem_count = len(evidence_ids)
        independent_count = results["A"]
        score = (200 * independent_count + problem_count) // (2 * problem_count) if problem_count else None
        topics.append({
            "tag": tag, "score": score, "independent_count": independent_count,
            "problem_count": problem_count,
            "stable_count": len(topic_problems[tag].intersection(stable_problems)),
            "sample_small": problem_count < 5, "results": results,
        })
    return {
        "language": selected_language, "basis": "self_reported",
        "metric": "independent_completion_rate", "score_version": SCORE_VERSION,
        "topics": topics,
    }
