"""Allocate configured per-category daily slots without relaxing any selection gate."""

from collections import Counter, defaultdict
from datetime import date, timedelta

from .policies import filter_catalog, validate_plan_candidates

PROFILE = "tokyo-interview-v1"
# Recorded review reasons that show a confirmed difficulty, not just elapsed time.
WEAK_REVIEW_REASONS = {"unfinished_or_assisted", "overtime_or_key_error", "same_day_assisted_learning"}


class _Pools:
    """Hold ordered category candidates and the reasons others were excluded."""

    def __init__(self) -> None:
        """Create empty category pools.

        Inputs: None.
        Outputs: A pool holder with ordered lists and reason counters.
        Logic: Keep each category separate so no slot borrows another pool.
        Dependencies: Counter and defaultdict.
        """
        self.items = defaultdict(list)
        self.reasons = defaultdict(Counter)
        self.next_due = {}
        self.ranker = {}

    def add(self, category: str, candidate: dict, frame: str | None = None, justified: bool = False) -> None:
        """Append one eligible candidate to a category.

        Inputs: A category, a candidate dictionary, its framework, and a sixth-slot flag.
        Outputs: None. Store the candidate in order.
        Logic: Builders add candidates in their profile's existing priority order.
        Dependencies: None.
        """
        self.items[category].append((candidate, frame, justified))

    def reject(self, category: str, reason: str) -> None:
        """Count one candidate that a hard gate excluded from a category.

        Inputs: A category and a stable reason code.
        Outputs: None. Increment the reason counter.
        Logic: Diagnostics report counts, never relaxed substitutes.
        Dependencies: Counter.
        """
        self.reasons[category][reason] += 1


def practiced_problem_ids(attempts: list[dict], context: dict) -> set[str]:
    """Collect problems with any recorded practice in any language.

    Inputs: All attempts and a selection context with optional stored practice IDs.
    Outputs: Problem IDs that cannot count as new work.
    Logic: Any attempt, checkpoint, or non-selection evidence means the problem was seen.
    Dependencies: Store-provided practiced_problem_ids.
    """
    return {attempt["problem_id"] for attempt in attempts} | set(context.get("practiced_problem_ids") or [])


def _weak_evidence(state: dict | None) -> bool:
    """Decide whether derived state records a confirmed weakness.

    Inputs: One problem state, or None.
    Outputs: True only for explicit A-D evidence or a difficulty review reason.
    Logic: Missing responses, deferrals, and skips never create weakness.
    Dependencies: WEAK_REVIEW_REASONS and derived weakness scores.
    """
    if not state:
        return False
    return state.get("weakness_score", 0) > 0 or state.get("review_reason") in WEAK_REVIEW_REASONS


def _note_not_due(pools: _Pools, category: str, due: str | None) -> None:
    """Record a weak problem that waits for its review date.

    Inputs: Pools, a category, and the problem's review date.
    Outputs: None. Update counters and the earliest future date.
    Logic: Spacing rules stay in force. Report the next date instead.
    Dependencies: _Pools.
    """
    pools.reject(category, "not_due" if due else "no_review_date")
    if due and (category not in pools.next_due or due < pools.next_due[category]):
        pools.next_due[category] = due


def _standard_pools(catalog: list[dict], attempts: list[dict], settings: dict, training_date: str,
                    state: dict, policy: dict, practiced: set[str]) -> _Pools:
    """Build category pools with the standard profile's eligibility rules.

    Inputs: Catalog, attempts, settings, date, state, policy, and practiced IDs.
    Outputs: Ordered pools for continue, weak, review, and new.
    Logic: Mirror standard parking, continuation order, and new-problem ranking.
    Dependencies: Standard rule helpers and policy filtering.
    """
    from .rules import _attempt_order, _date, _plus_days

    pools = _Pools()
    today = _date(training_date, "training_date")
    language = settings["language"]
    by_problem = {problem["id"]: problem for problem in filter_catalog(catalog, policy)}
    grouped = defaultdict(list)
    for attempt in sorted((item for item in attempts if item["language"] == language), key=_attempt_order):
        grouped[attempt["problem_id"]].append(attempt)
    parked, pending, open_problems = set(), [], set()
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
            if result in (None, "D", "E"):
                open_problems.add(problem_id)
            if result is None or result == "D":
                pending.append((0 if result == "D" else 1, planned or _attempt_order(attempt)[0], attempt.get("created_at") or "", attempt["id"], attempt))
            elif result == "E":
                deferred = feedback.get("defer_until")
                if deferred is not None and _date(deferred, "defer_until") <= today:
                    pending.append((0, planned or _attempt_order(attempt)[0], attempt.get("created_at") or "", attempt["id"], attempt))
                else:
                    parked.add(problem_id)
        feedback = history[-1].get("feedback") or {}
        if feedback.get("result") == "F":
            until = feedback.get("skip_until")
            until_day = _plus_days(_date(_attempt_order(history[-1])[0], "practice_date"), settings["skip_cooldown_days"]) if until is None else _date(until, "skip_until")
            if today < until_day:
                parked.add(problem_id)
    for _, _, _, _, attempt in sorted(pending):
        pools.add("continue", {"problem_id": attempt["problem_id"], "attempt_id": attempt["id"], "reason": "continue", "review_source_attempt_id": None})
    states = {item["problem_id"]: item for item in state["problems"] if item["language"] == language}
    due_items = []
    for problem_id, problem_state in states.items():
        if problem_id not in by_problem or problem_id in parked or problem_id in open_problems:
            continue
        category = "weak" if _weak_evidence(problem_state) else "review"
        due = problem_state["review_due"]
        if due is None or due > training_date:
            if category == "weak":
                _note_not_due(pools, "weak", due)
            continue
        due_items.append((due, problem_id, category, problem_state))
    for due, problem_id, category, problem_state in sorted(due_items):
        pools.add(category, {"problem_id": problem_id, "attempt_id": None, "reason": "retest", "review_source_attempt_id": problem_state["review_source_attempt_id"]})
    topic_scores = {item["tag"]: item["weakness_score"] for item in state["topics"] if item["language"] == language}
    for problem_id, problem in by_problem.items():
        if problem_id in practiced:
            pools.reject("new", "already_practiced")
            continue
        pools.add("new", problem)

    def rank(items: list, selected: list[dict]) -> list:
        """Order unpracticed problems with the standard greedy ranking.

        Inputs: Remaining new-pool entries and the candidates selected so far.
        Outputs: Entries in the order the standard profile would prefer them.
        Logic: Reuse weak-topic, preferred-topic, difficulty, overlap, and ID keys.
        Dependencies: Topic scores, policy preferences, and catalog tags.
        """
        covered = {tag for item in selected for tag in by_problem[item["problem_id"]]["tags"]}
        base_slot = len(selected) < settings["baseline_count"]

        def key(entry: tuple) -> tuple:
            """Score one entry. Inputs: a pool entry. Outputs: a sort key.

            Logic: Lower tuples rank first, matching the standard selector.
            Dependencies: The enclosing ranking context.
            """
            problem = entry[0]
            return (-sum(topic_scores.get(tag, 0) for tag in problem["tags"]),
                    -len(set(problem["tags"]).intersection(policy["preferred_topics"])),
                    int(problem["difficulty"] != ("easy" if base_slot else "medium")),
                    len(covered.intersection(problem["tags"])), int(problem["id"].split(":")[-1]), problem["id"])
        return sorted(items, key=key)

    def finish(entry: tuple, selected: list[dict]) -> dict:
        """Convert a chosen new problem into a standard candidate.

        Inputs: A pool entry and the candidates selected so far.
        Outputs: A candidate with the standard selection reason.
        Logic: Keep the standard reason vocabulary for plan items.
        Dependencies: Topic scores and policy preferences.
        """
        problem = entry[0]
        base_slot = len(selected) < settings["baseline_count"]
        if sum(topic_scores.get(tag, 0) for tag in problem["tags"]) > 0:
            reason = "weakness"
        elif set(problem["tags"]).intersection(policy["preferred_topics"]):
            reason = "preferred_topic"
        else:
            reason = "foundation" if base_slot else "representative"
        return {"problem_id": problem["id"], "attempt_id": None, "reason": reason, "review_source_attempt_id": None}

    pools.ranker["new"] = (rank, finish)
    return pools


def _profile_pools(catalog: list[dict], attempts: list[dict], settings: dict, training_date: str,
                   state: dict, policy: dict, context: dict, practiced: set[str]) -> _Pools:
    """Build category pools with the interview profile's evidence gates.

    Inputs: Catalog, attempts, settings, date, state, policy, research, and practiced IDs.
    Outputs: Ordered pools for continue, weak, review, and new.
    Logic: Mirror continuation identity, research, source, and weekly repeat rules.
    Dependencies: Interview profile helpers and policy filtering.
    """
    from .training_profile import (_completed_context, _day, _score_key, attempt_context,
                                   primary_framework, timebox, verified_sources)

    pools = _Pools()
    research = context.get("candidates", {})
    history = context.get("history") or []
    recent = context.get("recent_plan") or []
    today = date.fromisoformat(training_date)
    by_id = {problem["id"]: problem for problem in filter_catalog(catalog, policy)}
    states = {item["problem_id"]: item for item in state["problems"] if item["language"] == settings["language"]}
    parked, pending, all_records = set(), [], defaultdict(list)
    for attempt in attempts:
        if attempt["language"] != settings["language"]:
            continue
        all_records[attempt["problem_id"]].append(attempt)
        details = {**research.get(attempt["problem_id"], {}), **attempt_context(attempt)}
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
        if feedback.get("result") == "F" and (feedback.get("skip_until") is None or feedback["skip_until"] > training_date):
            parked.add(problem_id)
    for _, _, _, _, attempt, details in sorted(pending, key=lambda item: item[:4]):
        problem = by_id.get(attempt["problem_id"])
        if problem is None or attempt["problem_id"] in parked:
            continue
        frame = primary_framework(problem, attempt, details)
        if frame is None or not verified_sources(details):
            pools.reject("continue", "framework_missing" if frame is None else "source_unverified")
            continue
        box = timebox(details.get("training_identity") or attempt.get("kind"))
        pools.add("continue", {"problem_id": problem["id"], "attempt_id": attempt["id"], "reason": "continue", "review_source_attempt_id": None, "training_identity": box["identity"], "original_recommendation_date": details.get("original_recommendation_date") or attempt["planned_date"], "primary_framework": frame, "timebox": box, "score": details.get("score"), "source_verification": details.get("source_verification"), "source_checks": details.get("source_checks"), "source_verified": details.get("source_verified", True), "targeted_gap": details.get("targeted_gap")}, frame)
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    used_ids, used_frames = set(), set()
    for event in history:
        if week_start <= event["date"] < training_date:
            used_ids.add(event["problem_id"])
            if event["problem_id"] in by_id:
                used_frames.add(primary_framework(by_id[event["problem_id"]], context=event))
    ranked = []
    for problem_id, problem in by_id.items():
        if problem_id in parked:
            continue
        if any((item.get("feedback") or {}).get("result") in (None, "D", "E") and not _completed_context(item) for item in all_records[problem_id]):
            continue
        problem_state = states.get(problem_id)
        due = (problem_state or {}).get("review_due")
        is_due = due is not None and due <= training_date
        if problem_id in practiced:
            if not all_records[problem_id]:
                pools.reject("new", "practiced_other_language_or_evidence")
                continue
            category = "weak" if _weak_evidence(problem_state) else "review"
            if not is_due:
                if category == "weak":
                    _note_not_due(pools, "weak", due)
                continue
        else:
            category = "new"
        details = research.get(problem_id) or problem.get("training_context") or {}
        frame = primary_framework(problem, context=details)
        if frame is None:
            pools.reject(category, "framework_missing")
            continue
        if not verified_sources(details):
            pools.reject(category, "source_unverified")
            continue
        if details.get("score") is None:
            pools.reject(category, "research_missing")
            continue
        if details.get("transfer_from") is not None:
            pools.reject(category, "transfer_not_allocated")
            continue
        if category == "new" and problem_id in used_ids:
            pools.reject("new", "recommended_this_week")
            continue
        repeated = category == "new" and frame in used_frames
        if repeated and not details.get("weekly_repeat_justification"):
            pools.reject("new", "weekly_framework_repeat")
            continue
        identity = "new" if category == "new" else "retest"
        source = problem_state.get("review_source_attempt_id") if identity == "retest" else None
        candidate = {"problem_id": problem_id, "attempt_id": None, "reason": "retest" if identity == "retest" else "interview_value", "review_source_attempt_id": source, "training_identity": identity, "primary_framework": frame, "timebox": timebox(identity), "score": details.get("score"), "targeted_gap": details.get("targeted_gap"), "source_verification": details.get("source_verification"), "source_checks": details.get("source_checks"), "source_verified": details.get("source_verified", True), "transfer_from": None, "transfer_change": None, "weekly_repeat_justification": details.get("weekly_repeat_justification"), "sixth_justification": details.get("sixth_justification")}
        priority = (int(repeated),) + _score_key(details, problem, problem_state, due if is_due else None, today)
        ranked.append((priority, category, candidate, frame, bool(details.get("sixth_justification"))))
    for _, category, candidate, frame, justified in sorted(ranked, key=lambda item: item[0]):
        pools.add(category, candidate, frame, justified)
    return pools


def select_mixed(catalog: list[dict], attempts: list[dict], settings: dict, training_date: str,
                 state: dict, policy: dict, context: dict | None = None) -> dict:
    """Fill configured category slots and explain every shortfall.

    Inputs: Catalog, attempts, normalized settings with daily_mix, date, state, policy, and research.
    Outputs: Selected candidates plus per-category allocation diagnostics.
    Logic: Fill slots in configured order. A category never borrows another pool.
    Dependencies: Profile pool builders and final plan validation.
    """
    context = context or {}
    mix = settings["daily_mix"]
    profile = settings["training_profile"] == PROFILE
    practiced = practiced_problem_ids(attempts, context)
    if profile:
        pools = _profile_pools(catalog, attempts, settings, training_date, state, policy, context, practiced)
    else:
        pools = _standard_pools(catalog, attempts, settings, training_date, state, policy, practiced)
    capacity = settings["daily_count"]
    if policy["max_daily_count"] is not None:
        capacity = min(capacity, policy["max_daily_count"])
    if profile:
        capacity = min(capacity, 6)
    selected, chosen_ids, frameworks = [], set(), set()
    report = {}

    def take(category: str, count: int, fills_unused: bool = False) -> int:
        """Select up to count candidates from one category pool.

        Inputs: A category, the requested count, and a fill-unused marker.
        Outputs: The number of selected candidates.
        Logic: Apply duplicate, framework, capacity, and sixth-slot gates.
        Dependencies: The enclosing pools and selection state.
        """
        taken = 0
        reasons = pools.reasons[category]
        while taken < count:
            if len(selected) >= capacity:
                reasons["policy_cap_limited"] += count - taken
                break
            remaining = pools.items[category]
            ranker = pools.ranker.get(category)
            ordered = ranker[0](remaining, selected) if ranker else list(remaining)
            picked = None
            for entry in ordered:
                candidate, frame, justified = entry
                problem_id = candidate.get("problem_id") or candidate.get("id")
                if problem_id in chosen_ids:
                    reasons["already_selected"] += 1
                    remaining.remove(entry)
                    continue
                if profile and frame in frameworks:
                    reasons["framework_conflict"] += 1
                    remaining.remove(entry)
                    continue
                if profile and category != "continue" and len(selected) >= 5 and not justified:
                    reasons["sixth_justification_missing"] += 1
                    remaining.remove(entry)
                    continue
                picked = entry
                break
            if picked is None:
                break
            remaining.remove(picked)
            candidate = ranker[1](picked, selected) if ranker else dict(picked[0])
            selected.append(candidate)
            chosen_ids.add(candidate["problem_id"])
            if picked[1] is not None:
                frameworks.add(picked[1])
            report_entry = {"position": len(selected), "problem_id": candidate["problem_id"], "category": category}
            if fills_unused:
                report_entry["fills_unused"] = True
            allocation.append(report_entry)
            taken += 1
        return taken

    allocation = []
    categories = []
    continuations = [entry[0] for entry in pools.items["continue"]]
    for slot in mix["slots"]:
        got = take(slot["category"], slot["count"])
        categories.append({"category": slot["category"], "requested": slot["count"], "selected": got, "missing": slot["count"] - got})
    unused = sum(item["missing"] for item in categories if item["category"] != "continue")
    if mix["continuation"] == "fill_unused" and unused:
        take("continue", min(unused, capacity - len(selected)), fills_unused=True)
    for item in categories:
        reasons = dict(pools.reasons[item["category"]])
        if item["missing"] and not pools.items[item["category"]] and not reasons:
            reasons = {"no_eligible_candidates": 1}
        item["reasons"] = reasons
        if item["category"] in pools.next_due:
            item["next_due"] = pools.next_due[item["category"]]
    chosen_attempts = {item.get("attempt_id") for item in selected}
    backlog = [{"attempt_id": item["attempt_id"], "problem_id": item["problem_id"]}
               for item in continuations if item["attempt_id"] not in chosen_attempts]
    if profile:
        for position, candidate in enumerate(selected, 1):
            candidate["daily_role"] = "base" if position <= 4 else "supplement"
            candidate["mix_category"] = allocation[position - 1]["category"]
    validate_plan_candidates(selected, catalog, policy, settings)
    return {"selected": selected, "diagnostics": {
        "mode": "daily_mix", "continuation": mix["continuation"], "capacity": capacity,
        "categories": categories, "category_shortfalls": [item for item in categories if item["missing"]],
        "allocation": allocation, "unallocated_backlog": backlog}}
