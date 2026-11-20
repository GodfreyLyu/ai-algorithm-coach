"""Derive topic rates and practice progress from current self-reported evidence."""

from collections import defaultdict

from ..errors import CoachError

SCORE_VERSION = "1"
PROGRESS_VERSION = "1"
VALID_RESULTS = ("A", "B", "C", "D")
ALL_RESULTS = ("A", "B", "C", "D", "E", "F")


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


def _language(language: object) -> str:
    """Validate and trim a score language.

    Inputs: A candidate language value.
    Outputs: The trimmed language text.
    Logic: Reject empty or overlong values with the shared error contract.
    Dependencies: CoachError.
    """
    if not isinstance(language, str) or not language.strip() or len(language) > 40:
        raise CoachError("validation_error", "language must be non-empty text of at most 40 characters.")
    return language.strip()


def _latest_results(attempts: list[dict], known: dict, language: str) -> dict:
    """Select the newest A-D attempt for each known problem.

    Inputs: Effective attempts, catalog by ID, and a validated language.
    Outputs: A map from problem ID to its newest A-D attempt.
    Logic: Skip other languages, unknown problems, and E, F, or empty results.
    Dependencies: _practice_order.
    """
    latest = {}
    for attempt in attempts:
        feedback = attempt.get("feedback") or {}
        problem_id = attempt["problem_id"]
        if attempt["language"] != language or problem_id not in known:
            continue
        if feedback.get("result") not in VALID_RESULTS:
            continue
        previous = latest.get(problem_id)
        if previous is None or _practice_order(attempt) > _practice_order(previous):
            latest[problem_id] = attempt
    return latest


def _stable_problems(problem_states: list[dict], language: str) -> set:
    """Collect stable problem IDs for one language.

    Inputs: Existing problem states and a validated language.
    Outputs: The IDs whose saved mastery status is stable.
    Logic: Read saved mastery only. Do not apply new mastery rules.
    Dependencies: The learning projection contract.
    """
    return {
        state["problem_id"] for state in problem_states
        if state["language"] == language and state.get("mastery_status") == "stable"
    }


def derive_topic_scores(attempts: list[dict], catalog: list[dict], language: str, problem_states: list[dict]) -> dict:
    """Compute per-topic independent completion rates from distinct problems.

    Inputs: Effective attempts, stored catalog, language, and existing problem states.
    Outputs: Topic scores, result counts, sample flags, and explicit score provenance.
    Logic: Use the newest A-D attempt per problem. Round half up using integers.
    Dependencies: Catalog tags and existing mastery states; no writes or new mastery rules.
    """
    selected_language = _language(language)
    known = {problem["id"]: problem for problem in catalog}
    latest = _latest_results(attempts, known, selected_language)
    stable_problems = _stable_problems(problem_states, selected_language)
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


def derive_practice_progress(attempts: list[dict], catalog: list[dict], language: str, problem_states: list[dict]) -> dict:
    """Summarize daily practice activity and per-problem latest results.

    Inputs: Effective attempts, stored catalog, language, and existing problem states.
    Outputs: Daily result counts and minutes, plus problems with A-D evidence.
    Logic: Count each attempt's current result once on its practice date.
      Problem rows reuse the newest A-D rule from topic scores.
    Dependencies: _latest_results and saved mastery; no writes or new rules.
    """
    selected_language = _language(language)
    known = {problem["id"]: problem for problem in catalog}
    days = {}
    attempt_counts = defaultdict(int)
    for attempt in attempts:
        result = (attempt.get("feedback") or {}).get("result")
        if attempt["language"] != selected_language or attempt["problem_id"] not in known or result not in ALL_RESULTS:
            continue
        attempt_counts[attempt["problem_id"]] += 1
        day = attempt.get("practice_date") or attempt.get("planned_date") or attempt.get("created_on")
        entry = days.setdefault(day, {"date": day, "results": dict.fromkeys(ALL_RESULTS, 0), "minutes": 0})
        entry["results"][result] += 1
        minutes = attempt["feedback"].get("elapsed_minutes")
        if isinstance(minutes, (int, float)) and not isinstance(minutes, bool):
            entry["minutes"] += minutes
    latest = _latest_results(attempts, known, selected_language)
    stable_problems = _stable_problems(problem_states, selected_language)
    problems = []
    for problem_id in sorted(latest):
        problem = known[problem_id]
        attempt = latest[problem_id]
        problems.append({
            "problem_id": problem_id, "title": problem["title"], "difficulty": problem["difficulty"],
            "url": problem["url"], "tags": sorted(set(problem["tags"])),
            "result": attempt["feedback"]["result"],
            "practice_date": attempt.get("practice_date") or attempt.get("planned_date"),
            "attempt_count": attempt_counts[problem_id], "stable": problem_id in stable_problems,
        })
    return {
        "language": selected_language, "basis": "self_reported",
        "progress_version": PROGRESS_VERSION,
        "days": [days[day] for day in sorted(days)], "problems": problems,
    }
