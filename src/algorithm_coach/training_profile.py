"""Apply the versioned interview profile without model or network calls."""

from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
import math

from .errors import CoachError
from .policies import filter_catalog, validate_plan_candidates


PROFILE = "tokyo-interview-v1"
SCORE_LIMITS = (40, 30, 15, 10, 5)
TIMEBOXES = {"new": (20, 30), "retest": (10, 15), "transfer": (15, 25)}
RESEARCH_FIELDS = {
    "primary_framework", "framework", "source_verified", "source_verification",
    "source_checks", "score", "score_total", "score_date", "targeted_gap",
    "targeted_gap_evidence", "sixth_justification", "weekly_repeat_justification",
    "transfer_from", "transfer_change", "comparison", "candidate_comparison",
    "selection_reason", "reason", "focused_improvement_check", "pass_criteria",
    "non_spoiler_hint", "display_goal", "interview_value", "technical_checks",
    "source_caveat", "framework_technique", "prerequisites", "evidence_references",
    "target_complexity", "target_complexity_internal", "target_complexity_notes",
    "review_priority_reason", "api_notes", "framework_notes",
}


def timebox(identity: str) -> dict:
    """Return the canonical practice timebox, including closed-book recall.

    Inputs: A canonical identity or the current core's practice kind.
    Outputs: Inclusive minute limits and the canonical identity.
    Logic: Translate internal practice kinds once and preserve their budget.
    Dependencies: TIMEBOXES.
    """
    normalized = {"practice": "new", "review": "retest", "redo": "retest"}.get(identity, identity)
    lower, upper = TIMEBOXES[normalized]
    return {"identity": normalized, "min": lower, "max": upper, "includes_closed_book_recall": True}


def attempt_context(attempt: dict | None) -> dict:
    """Read the native context of one practice attempt.

    Inputs: An optional current-schema attempt.
    Outputs: Its independent context dictionary.
    Logic: Keep engine-owned practice facts separate from problem research.
    Dependencies: deepcopy.
    """
    return deepcopy(attempt.get("training_context", {})) if attempt is not None else {}


def primary_framework(problem: dict, attempt: dict | None = None, context: dict | None = None) -> str | None:
    """Resolve a conservative primary framework for daily conflict checks.

    Inputs: Public metadata, an optional attempt, and host-supplied context.
    Outputs: A normalized framework, or None when no basis exists.
    Logic: Prefer explicit labels and collapse known equivalent framework names.
    Dependencies: attempt_context; labels are metadata rather than mastery claims.
    """
    details = {**attempt_context(attempt), **(problem.get("training_context") or {}), **(context or {})}
    label = details.get("primary_framework") or details.get("framework")
    aliases = (
        (("单调栈", "monotonic-stack"), "monotonic-stack"),
        (("单调队列", "monotonic-queue"), "monotonic-queue"),
        (("前缀", "prefix-sum"), "prefix-sum"),
        (("差分", "difference-array"), "difference-array"),
        (("滑动", "sliding-window"), "sliding-window"),
        (("双指针", "two-pointers"), "two-pointers"),
        (("二分", "binary-search"), "binary-search"),
        (("链表", "linked-list"), "linked-list"),
        (("拓扑", "topological"), "topological-sort"),
        (("并查集", "union-find"), "union-find"),
        (("回溯", "backtracking"), "backtracking"),
        (("动态规划", "dynamic-programming"), "dynamic-programming"),
        (("贪心", "greedy"), "greedy"),
        (("区间", "interval"), "interval"),
        (("堆", "heap"), "heap"),
        (("矩阵", "matrix"), "matrix"),
    )
    if isinstance(label, str) and label.strip():
        normalized = label.strip().lower().replace("_", "-")
        for needles, canonical in aliases:
            if any(needle in normalized for needle in needles):
                return canonical
        if "二叉树" in normalized or "tree" in normalized or "bst" in normalized:
            return "tree"
        if "图" in normalized or "graph" in normalized:
            return "graph"
        return normalized
    tags = problem.get("tags") or []
    for tag in ("monotonic-stack", "sliding-window", "prefix-sum", "binary-search", "linked-list", "heap", "backtracking", "dynamic-programming", "greedy", "tree", "graph", "two-pointers", "stack", "hash-table", "matrix"):
        if tag in tags:
            return tag
    return None


def validate_score(value: object) -> list[float] | None:
    """Validate the five bounded interview-efficiency dimensions.

    Inputs: A list of five numeric dimension scores, or missing data.
    Outputs: An independent valid list, None, or a validation error.
    Logic: Reject booleans, non-finite numbers, and scores beyond each weight.
    Dependencies: SCORE_LIMITS, math, and CoachError.
    """
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 5:
        raise CoachError("validation_error", "Interview scores need five dimensions.")
    for score, maximum in zip(value, SCORE_LIMITS):
        if type(score) not in (int, float) or not 0 <= score <= maximum or not math.isfinite(score):
            raise CoachError("validation_error", "An interview score exceeds its dimension limit.")
    return list(value)



def validate_training_context(context: dict) -> dict:
    """Validate host research without converting it to practice evidence.

    Inputs: A structured context object for a catalog problem or saved plan item.
    Outputs: An independent normalized context, or a validation error.
    Logic: Check scores, labels, dates, and source flags while retaining research details.
    Dependencies: validate_score, date, deepcopy, and CoachError.
    """
    if not isinstance(context, dict) or not all(isinstance(key, str) for key in context):
        raise CoachError("validation_error", "Training context must be an object with text keys.")
    unknown = set(context) - RESEARCH_FIELDS
    if unknown:
        raise CoachError("validation_error", "Training research cannot change practice outcomes, checkpoints, original dates, or identities.", {"unsupported_fields": sorted(unknown)})
    normalized = deepcopy(context)
    for field in ("primary_framework", "framework", "targeted_gap", "sixth_justification", "weekly_repeat_justification", "transfer_from", "transfer_change"):
        value = normalized.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 4000):
            raise CoachError("validation_error", f"{field} must be non-empty text of at most 4000 characters.")
    if "source_verified" in normalized and type(normalized["source_verified"]) is not bool:
        raise CoachError("validation_error", "source_verified must be true or false.")
    if "source_verification" in normalized and not isinstance(normalized["source_verification"], dict):
        raise CoachError("validation_error", "source_verification must be an object.")
    if "source_checks" in normalized and not isinstance(normalized["source_checks"], (dict, list)):
        raise CoachError("validation_error", "source_checks must be an object or array.")
    if "score" in normalized:
        normalized["score"] = validate_score(normalized["score"])
    if "score_total" in normalized:
        scores = normalized.get("score")
        total = normalized["score_total"]
        if scores is None or type(total) not in (int, float) or total != sum(scores):
            raise CoachError("validation_error", "score_total must equal the five supplied dimensions.")
    return normalized

def _day(attempt: dict) -> str:
    """Resolve the occurrence date for one effective attempt.

    Inputs: An attempt projection.
    Outputs: Its ISO practice date.
    Logic: Use practice time before administrative recommendation time.
    Dependencies: Stored attempt fields.
    """
    return attempt.get("practice_date") or attempt.get("planned_date") or attempt.get("created_on")


def _assessment(attempt: dict) -> dict:
    """Combine explicit oral evidence with scoped host assessments.

    Inputs: An attempt containing feedback and an optional assessment.
    Outputs: Proof flags and explicit regression indicators.
    Logic: Missing proof remains unknown and one scoped review implies no other proof.
    Dependencies: attempt_context.
    """
    feedback = attempt.get("feedback") or {}
    context = attempt_context(attempt)
    result = dict(attempt.get("assessment") or {})
    for target, field in (("invariant", "can_explain_invariant"), ("correctness", "can_explain_correctness"), ("complexity", "can_explain_complexity"), ("boundary", "boundary_tests")):
        if target not in result and type(feedback.get(field)) is bool:
            result[target] = feedback[field]
    result["timebox"] = timebox(context.get("training_identity") or attempt.get("kind") or "new")
    minutes = feedback.get("elapsed_minutes")
    if type(minutes) in (int, float):
        result["on_time"] = minutes <= result["timebox"]["max"]
    return result


def _stable(attempt: dict) -> bool:
    """Require all recorded stable-pass criteria for one independent attempt.

    Inputs: An effective attempt and its scoped evidence.
    Outputs: True only for a qualifying independently completed practice.
    Logic: Require on-time A plus invariant, correctness, complexity and boundary evidence.
    Dependencies: _assessment.
    """
    feedback = attempt.get("feedback") or {}
    evidence = _assessment(attempt)
    return feedback.get("result") == "A" and feedback.get("assistance") in (None, "none") and feedback.get("hint_level") in (None, "none") and evidence.get("on_time") is True and all(evidence.get(key) is True for key in ("invariant", "correctness", "complexity", "boundary")) and evidence.get("key_error") is not True and evidence.get("severe_dependence") is not True


def _review_interval(attempt: dict) -> tuple[int, tuple[int, int], str]:
    """Choose a review interval from the confirmed performance band.

    Inputs: An effective attempt with feedback and scoped evidence.
    Outputs: Concrete days, allowed range, and an inspectable reason.
    Logic: Prioritize dependence and errors, then time and explanation evidence.
    Dependencies: _assessment and _stable.
    """
    feedback = attempt.get("feedback") or {}
    evidence = _assessment(attempt)
    result = feedback.get("result")
    proficiency = feedback.get("proficiency")
    if result in {"B", "C", "D"} or evidence.get("severe_dependence") is True:
        band, reason = (1, 3), "unfinished_or_assisted"
    elif evidence.get("key_error") is True or evidence.get("on_time") is False:
        band, reason = (3, 7), "overtime_or_key_error"
    elif not _stable(attempt):
        band, reason = (7, 14), "explanation_or_boundary_unconfirmed"
    else:
        band, reason = (14, 30), "independent_on_time_with_explanation"
    days = band[0] if type(proficiency) is not int or proficiency <= 2 else (sum(band) // 2 if proficiency == 3 else band[1])
    return days, band, reason


def assessment_version(attempt: dict) -> str:
    """Identify the scoped assessment used by a learning decision.

    Inputs: An attempt with a store-provided evidence version or scoped proof.
    Outputs: A stable comparison value.
    Logic: Prefer the store's code/review identity, including pending code changes.
    Dependencies: canonical JSON and SHA-256 for standalone rule calls.
    """
    if "assessment_version" in attempt:
        return attempt["assessment_version"]
    from .storage import canonical_json
    import hashlib

    return hashlib.sha256(canonical_json(attempt.get("assessment", {})).encode()).hexdigest()


def learning_outcome(attempt: dict) -> dict:
    """Describe the current learning outcome of an attempt.

    Inputs: One effective attempt.
    Outputs: Result, date, identity, scoped stability, and review decision.
    Logic: Use facts from the bound feedback and its native practice context.
    Dependencies: _day, _stable, and timebox.
    """
    result = (attempt.get("feedback") or {}).get("result")
    decision = None
    if result in {"A", "B", "C", "D"}:
        days, interval, reason = _review_interval(attempt)
        decision = {"days": days, "range": list(interval), "reason": reason}
    return {"result": result, "practice_date": _day(attempt),
            "training_identity": timebox(attempt_context(attempt).get("training_identity") or attempt["kind"])["identity"],
            "stable_pass": _stable(attempt), "review_decision": decision}


def _review_dates(outcomes: dict) -> set[str]:
    """Collect dates with a completed retest or framework transfer.

    Inputs: Effective attempt outcomes.
    Outputs: Distinct completed-review dates.
    Logic: Several revisions or rewrites on one date do not add several reviews.
    Dependencies: The canonical outcome contract.
    """
    return {item["practice_date"] for item in outcomes.values()
            if item["result"] in {"A", "B", "C"} and item["training_identity"] in {"retest", "transfer"}}


def _problem_state(records: list[dict], checkpoint: dict | None) -> dict:
    """Derive one problem's learning state from native evidence.

    Inputs: Ordered attempts and an optional confirmed learning checkpoint.
    Outputs: Current counts, review decision, and evidence-coverage diagnostics.
    Logic: Retain unchanged checkpoints and apply new evidence once per date.
    Dependencies: Scoped assessments, canonical outcomes, and date arithmetic.
    """
    ability = [item for item in records if (item.get("feedback") or {}).get("result") in {"A", "B", "C", "D"}]
    current = {item["id"]: learning_outcome(item) for item in records}
    checkpoint_state = deepcopy(checkpoint["state"]) if checkpoint else {}
    covered = checkpoint["feedback_revisions"] if checkpoint else {}
    previous = checkpoint["outcomes"] if checkpoint else {}
    version_changes = [item for item in records if
               (item["id"] not in covered and item.get("revision", 0) > 0) or
               (item["id"] in covered and
                (item.get("revision", 0) != covered[item["id"]] or
                 assessment_version(item) != checkpoint["assessment_versions"][item["id"]]))]
    changed = [item for item in version_changes if current[item["id"]] != previous.get(item["id"])]
    if checkpoint and not changed:
        return {**checkpoint_state, "evidence_coverage": checkpoint["evidence_coverage"]}
    if checkpoint and checkpoint["evidence_coverage"] == "complete":
        return _problem_state(records, None)

    cutoff = checkpoint_state.get("last_practice_date")
    historical_changes = [item for item in changed if item["id"] in covered and cutoff and _day(item) < cutoff]
    reconciliation = bool(historical_changes) or checkpoint_state.get("reconciliation_required", False)
    completed = checkpoint_state.get("completed_count", 0)
    independent = checkpoint_state.get("independent_count", 0)
    if checkpoint:
        for item in changed:
            before = previous.get(item["id"], {"result": None})["result"]
            after = current[item["id"]]["result"]
            completed += int(after in {"A", "B", "C"}) - int(before in {"A", "B", "C"})
            independent += int(after == "A") - int(before == "A")
    else:
        completed = sum(item["feedback"]["result"] in {"A", "B", "C"} for item in ability)
        independent = sum(item["feedback"]["result"] == "A" for item in ability)

    review_count = checkpoint_state.get("review_count", 0)
    if checkpoint:
        old_dates = _review_dates(previous)
        new_dates = _review_dates(current)
        review_count += len(new_dates - old_dates) - len(old_dates - new_dates)
    else:
        review_count = len(_review_dates(current))
    streak = checkpoint_state.get("consecutive_stable_passes", 0)
    due = checkpoint_state.get("review_due")
    due_source = checkpoint_state.get("review_source_attempt_id")
    band = checkpoint_state.get("review_interval_range")
    reason = checkpoint_state.get("review_reason")
    stable_dates = set(checkpoint.get("stable_dates", [])) if checkpoint else set()
    if cutoff and streak:
        stable_dates.add(cutoff)
    assisted_days = {_day(item) for item in ability if item["feedback"]["result"] in {"B", "C"} or _assessment(item).get("severe_dependence") is True}
    replay = changed if checkpoint else records
    for item in replay:
        outcome = current[item["id"]]
        result = outcome["result"]
        proof = _assessment(item)
        day = outcome["practice_date"]
        covered_change = checkpoint is not None and item["id"] in covered
        if covered_change and cutoff and day < cutoff:
            continue
        if covered_change and cutoff and day == cutoff:
            streak = 0
            stable_dates.clear()
        if result not in {"A", "B", "C", "D"}:
            if covered_change:
                streak, due, due_source, band = 0, None, None, None
                reason = "completion_retracted"
            continue
        if outcome["stable_pass"] and day not in assisted_days:
            if day not in stable_dates:
                streak += 1
                stable_dates.add(day)
        elif result in {"B", "C", "D"} or proof.get("key_error") is True or any(proof.get(key) is False for key in ("invariant", "correctness", "complexity", "boundary")):
            streak = 0
            stable_dates.clear()
        days, interval, reason = _review_interval(item)
        if day in assisted_days:
            days, interval, reason = 1, (1, 3), "same_day_assisted_learning"
        due = (date.fromisoformat(day) + timedelta(days=days)).isoformat()
        due_source, band = item["id"], list(interval)
    if reconciliation:
        streak, due, due_source, band = 0, None, None, None
        reason = "checkpoint_correction_requires_reconciliation"
    latest = ability[-1] if ability else None
    weakness = max(0, sum({"A": -1, "B": 1, "C": 2, "D": 3}[item["feedback"]["result"]] for item in ability[-5:]))
    mastery = "stable" if streak >= 2 else "independent" if latest is not None and latest["feedback"]["result"] == "A" else "learning" if ability or checkpoint else "unseen"
    evidence = list(checkpoint_state.get("evidence", []))
    current_ids = set(current)
    active_ids = {item["id"] for item in ability}
    evidence = [identity for identity in evidence if identity not in current_ids or identity in active_ids]
    evidence.extend(item["id"] for item in ability if item["id"] not in evidence)
    first = records[0]
    return {"problem_id": first["problem_id"], "language": first["language"],
            "completed_count": completed, "independent_count": independent,
            "mastery_status": mastery, "weakness_score": weakness,
            "review_due": due, "review_source_attempt_id": due_source,
            "evidence": evidence, "last_result": latest["feedback"]["result"] if latest else None,
            "last_practice_date": _day(latest) if latest else checkpoint_state.get("last_practice_date"),
            "consecutive_stable_passes": streak, "transfer_eligible": streak >= 2,
            "review_interval_range": band, "review_reason": reason, "review_count": review_count,
            "evidence_coverage": checkpoint["evidence_coverage"] if checkpoint else "complete",
            "reconciliation_required": reconciliation,
            "reconciliation_reason": "A checkpoint-covered earlier performance changed; complete replay evidence is unavailable." if reconciliation else None,
            "prior_review_due": checkpoint_state.get("review_due") if reconciliation else None}


def derive_profile_state(attempts: list[dict], config: dict, catalog: list[dict]) -> dict:
    """Derive interview learning state from current-schema records.

    Inputs: Effective attempts, normalized settings, and public problem metadata.
    Outputs: Problem states, topic weaknesses, and a versioned evidence basis.
    Logic: Group by problem and language, then apply native evidence and checkpoints.
    Dependencies: _problem_state and catalog tags.
    """
    groups = defaultdict(list)
    for attempt in attempts:
        groups[(attempt["problem_id"], attempt["language"])].append(attempt)
    by_id = {problem["id"]: problem for problem in catalog}
    problems, topics = [], {}
    for (problem_id, language), records in sorted(groups.items()):
        records = sorted(records, key=lambda item: (_day(item), item.get("occurred_at") or "", item["id"]))
        checkpoint = next((item["learning_checkpoint"] for item in records if "learning_checkpoint" in item), None)
        if checkpoint is not None and checkpoint["rule_version"] != PROFILE:
            raise CoachError("checkpoint_rule_mismatch", "The learning checkpoint uses another rule version.",
                             {"expected": PROFILE, "actual": checkpoint["rule_version"]})
        state = _problem_state(records, checkpoint)
        problems.append(state)
        for tag in by_id.get(problem_id, {}).get("tags", []):
            topic = topics.setdefault((tag, language), {"tag": tag, "language": language, "weakness_score": 0, "evidence": []})
            topic["weakness_score"] += state["weakness_score"]
            if state["weakness_score"]:
                topic["evidence"].extend(state["evidence"])
    return {"problems": problems, "topics": [topics[key] for key in sorted(topics)], "rule_version": PROFILE, "basis": "self_reported_with_scoped_assessments"}


def verified_sources(context: dict) -> bool:
    """Check whether source research was explicitly supplied by the host.

    Inputs: Structured candidate or original selection context.
    Outputs: True for recorded host verification; never for a URL alone.
    Logic: Use recorded source checks without inventing new checks.
    Dependencies: None.
    """
    if "source_verified" in context and context["source_verified"] is not True:
        return False
    verification = context.get("source_verification")
    checks = context.get("source_checks")
    return (isinstance(verification, dict) and bool(verification)) or (isinstance(checks, (dict, list)) and bool(checks))


def _completed_context(attempt: dict) -> bool:
    """Recognize native lifecycle facts without inventing an AC result.

    Inputs: One current-schema attempt.
    Outputs: Whether the record is closed or evidence-only.
    Logic: A newer feedback revision can retract a bound completion disposition.
    Dependencies: Native training context and feedback revision.
    """
    context = attempt_context(attempt)
    disposition = context.get("disposition", "open")
    return disposition == "record_only" or (disposition == "completed" and
            context["disposition_revision"] == attempt.get("revision", 0))


def _score_key(context: dict, problem: dict, state: dict | None, due: str | None, today: date) -> tuple:
    """Rank free slots by recorded efficiency and review needs.

    Inputs: Candidate research, metadata, problem state, due date, and today.
    Outputs: A deterministic comparison tuple.
    Logic: Compare explicit weighted scores and forgetting risk without fixed quotas.
    Dependencies: Validated research scores and datetime.
    """
    scores = context.get("score")
    total = sum(scores) if scores is not None else 0
    overdue = (today - date.fromisoformat(due)).days if due else 0
    weakness = (state or {}).get("weakness_score", 0)
    return (-total, -weakness, -overdue, int(problem.get("difficulty") != "medium"), problem["id"])


def select_profile_candidates(catalog: list[dict], attempts: list[dict], config: dict, training_date: str, state: dict, policy: dict, selection_context: dict | None = None) -> list[dict]:
    """Choose bounded interview work with shared scope and framework constraints.

    Inputs: Metadata, attempts, settings, date, state, policy, and saved host research.
    Outputs: Ordered candidates with original identity, role, score and timebox.
    Logic: Continue known rounds first, then compare eligible research and due reviews.
    Dependencies: Scope filtering, profile evidence, and deterministic helpers.
    """
    context = selection_context or {}
    research = context.get("candidates", {})
    history = context.get("history") or []
    recent = context.get("recent_plan") or []
    today = date.fromisoformat(training_date)
    capacity = min(6, config["daily_count"], policy["max_daily_count"] or 6)
    by_id = {problem["id"]: problem for problem in filter_catalog(catalog, policy)}
    states = {item["problem_id"]: item for item in state["problems"] if item["language"] == config["language"]}
    selected, selected_ids, frameworks, parked = [], set(), set(), set()
    pending = []
    all_records = defaultdict(list)
    for attempt in attempts:
        if attempt["language"] != config["language"]:
            continue
        all_records[attempt["problem_id"]].append(attempt)
        original = attempt_context(attempt)
        details = {**research.get(attempt["problem_id"], {}), **original}
        for field, value in research.get(attempt["problem_id"], {}).items():
            if details.get(field) is None:
                details[field] = value
        result = (attempt.get("feedback") or {}).get("result")
        if _day(attempt) > training_date:
            parked.add(attempt["problem_id"])
            continue
        if _completed_context(attempt):
            continue
        if result in (None, "D", "E"):
            defer = (attempt.get("feedback") or {}).get("defer_until")
            if result == "E" and defer is not None and defer > training_date:
                parked.add(attempt["problem_id"])
                continue
            order = recent.index(attempt["id"]) if attempt["id"] in recent else len(recent)
            pending.append((order, details.get("original_recommendation_date") or attempt["planned_date"], details.get("position") or 10000, attempt["id"], attempt, details))
    for problem_id, records in all_records.items():
        latest = max(records, key=lambda item: (_day(item), item.get("occurred_at") or "", item["id"]))
        feedback = latest.get("feedback") or {}
        if feedback.get("result") == "F":
            until = feedback.get("skip_until")
            if until is None or until > training_date:
                parked.add(problem_id)

    for _, _, _, _, attempt, details in sorted(pending, key=lambda item: item[:4]):
        problem_id = attempt["problem_id"]
        problem = by_id.get(problem_id)
        if problem is None or problem_id in selected_ids or problem_id in parked or len(selected) >= capacity:
            continue
        frame = primary_framework(problem, attempt, details)
        if frame is None or frame in frameworks or not verified_sources(details):
            continue
        box = timebox(details.get("training_identity") or attempt.get("kind"))
        selected.append({"problem_id": problem_id, "attempt_id": attempt["id"], "reason": "continue", "review_source_attempt_id": None, "training_identity": box["identity"], "original_recommendation_date": details.get("original_recommendation_date") or attempt["planned_date"], "primary_framework": frame, "timebox": box, "score": details.get("score"), "source_verification": details.get("source_verification"), "source_checks": details.get("source_checks"), "source_verified": details.get("source_verified", True), "targeted_gap": details.get("targeted_gap")})
        selected_ids.add(problem_id)
        frameworks.add(frame)

    week_start = (today - timedelta(days=today.weekday())).isoformat()
    used_ids, used_frames = set(), set()
    for event in history:
        event_day = event["date"]
        if week_start <= event_day < training_date:
            problem_id = event["problem_id"]
            used_ids.add(problem_id)
            if problem_id in by_id:
                used_frames.add(primary_framework(by_id[problem_id], context=event))
    pool = []
    for problem_id, problem in by_id.items():
        if problem_id in selected_ids or problem_id in parked:
            continue
        details = research.get(problem_id) or problem.get("training_context") or {}
        problem_state = states.get(problem_id)
        due = (problem_state or {}).get("review_due")
        is_due = due is not None and due <= training_date
        if all_records[problem_id] and not is_due:
            continue
        if any((item.get("feedback") or {}).get("result") in (None, "D", "E") and not _completed_context(item) for item in all_records[problem_id]):
            continue
        scores = details.get("score")
        frame = primary_framework(problem, context=details)
        if frame is None or not verified_sources(details) or scores is None:
            continue
        transfer_from = details.get("transfer_from")
        if transfer_from is not None:
            source_problem = by_id.get(transfer_from)
            source_attempts = sorted(all_records.get(transfer_from, []), key=lambda item: (_day(item), item["id"]))
            source_attempt = source_attempts[-1] if source_attempts else None
            source_frame = primary_framework(source_problem, source_attempt, research.get(transfer_from)) if source_problem else None
            if not states.get(transfer_from, {}).get("transfer_eligible") or source_frame != frame or not details.get("transfer_change"):
                continue
            identity = "transfer"
        else:
            identity = "retest" if is_due else "new"
        if identity == "new" and problem_id in used_ids:
            continue
        repeated_frame = identity == "new" and frame in used_frames
        if repeated_frame and not details.get("weekly_repeat_justification"):
            continue
        priority = (int(repeated_frame),) + _score_key(details, problem, problem_state, due if is_due else None, today)
        pool.append((priority, problem, details, identity, frame))
    for _, problem, details, identity, frame in sorted(pool, key=lambda item: item[0]):
        if len(selected) >= capacity:
            break
        if frame in frameworks:
            continue
        if len(selected) >= 5 and not details.get("sixth_justification"):
            continue
        problem_id = problem["id"]
        source = states.get(problem_id, {}).get("review_source_attempt_id") if identity == "retest" else None
        selected.append({"problem_id": problem_id, "attempt_id": None, "reason": "retest" if identity == "retest" else "transfer" if identity == "transfer" else "interview_value", "review_source_attempt_id": source, "training_identity": identity, "primary_framework": frame, "timebox": timebox(identity), "score": details.get("score"), "targeted_gap": details.get("targeted_gap"), "source_verification": details.get("source_verification"), "source_checks": details.get("source_checks"), "source_verified": details.get("source_verified", True), "transfer_from": details.get("transfer_from"), "transfer_change": details.get("transfer_change"), "weekly_repeat_justification": details.get("weekly_repeat_justification"), "sixth_justification": details.get("sixth_justification")})
        selected_ids.add(problem_id)
        frameworks.add(frame)
    for position, candidate in enumerate(selected, 1):
        candidate["daily_role"] = "base" if position <= 4 else "supplement"
    validate_plan_candidates(selected, catalog, policy, config)
    return selected
