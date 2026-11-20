"""Expose the local training loop through one transactional application service."""

from datetime import date, datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

from .core.catalog import CATALOG_VERSION, PROBLEMS
from .store.complexity import ComplexityMixin
from .errors import CoachError
from .core.policies import eligibility, validate_plan_candidates
from .store.policy_store import PolicyMixin
from .store.records import PracticeRecordsMixin
from .core.rules import NON_LEARNING_FIELDS, default_config, derive_learning_state, merge_feedback, validate_config
from .core.scoring import derive_practice_progress, derive_topic_scores
from .store import storage


def _now() -> str:
    """Inputs: none. Outputs: the current UTC timestamp.

    Logic: format a timezone-aware clock reading as ISO text.
    Dependencies: the operating system clock.
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _identifier(value: object, label: str) -> str:
    """Inputs: a value and field label. Outputs: a validated identifier.

    Logic: reject empty, oversized, or non-text identifiers.
    Dependencies: CoachError for client-safe validation errors.
    """
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise CoachError("validation_error", f"{label} must be non-empty text of at most 200 characters.")
    return value


def _iso_date(value: object) -> str:
    """Inputs: a date value. Outputs: canonical YYYY-MM-DD text.

    Logic: parse and reject alternate or invalid date formats.
    Dependencies: Python's date parser.
    """
    if not isinstance(value, str):
        raise CoachError("validation_error", "Training date must use YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise CoachError("validation_error", "Training date must use YYYY-MM-DD.") from exc
    if parsed.isoformat() != value:
        raise CoachError("validation_error", "Training date must use YYYY-MM-DD.")
    return value


def _timestamp(value: object) -> str:
    """Inputs: an ISO timestamp. Outputs: normalized UTC text.

    Logic: require an explicit offset and normalize the instant.
    Dependencies: Python's datetime parser.
    """
    if not isinstance(value, str):
        raise CoachError("validation_error", "occurred_at must be an ISO timestamp with an offset.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CoachError("validation_error", "occurred_at must be an ISO timestamp with an offset.") from exc
    if parsed.tzinfo is None:
        raise CoachError("validation_error", "occurred_at needs an explicit timezone offset.")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


class Coach(ComplexityMixin, PracticeRecordsMixin, PolicyMixin):
    """Own one local database and expose framework-independent use cases."""

    def __init__(self, db_path: Path) -> None:
        """Inputs: a database path. Outputs: a lazy service instance.

        Logic: retain the path without creating a file or directory.
        Dependencies: local filesystem paths; no database is opened yet.
        """
        self.path = Path(db_path).expanduser()
        self._connection: sqlite3.Connection | None = None

    def close(self) -> None:
        """Inputs: none. Outputs: none.

        Logic: release any cached database connection.
        Dependencies: the optional SQLite connection.
        """
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _db(self) -> sqlite3.Connection:
        """Inputs: none. Outputs: a supported database connection.

        Logic: open lazily and retain the validated connection.
        Dependencies: storage.connect and an initialized local database.
        """
        if self._connection is None:
            self._connection = storage.connect(self.path)
        return self._connection

    def initialize(self, config: dict | None = None) -> dict:
        """Inputs: optional initial configuration overrides. Outputs: init status.

        Logic: validate, create a private store, and seed metadata in one transaction.
        Dependencies: catalog metadata, pure rules, and local SQLite storage.
        """
        if config is not None and not isinstance(config, dict):
            raise CoachError("validation_error", "Configuration must be an object.")
        merged = default_config()
        merged.update(config or {})
        merged = validate_config(merged)
        if self.path.exists() or self.path.is_symlink():
            try:
                self._db()
            except CoachError as exc:
                if exc.code != "unsupported_database":
                    raise
            else:
                return self._existing_initialization(merged, config is not None)
        try:
            self._connection = storage.create(self.path)
        except CoachError as exc:
            if exc.code != "already_initialized":
                raise
            return self._existing_initialization(merged, config is not None)
        connection = self._connection
        try:
            connection.execute("INSERT INTO metadata VALUES (?, ?)", ("workspace_id", str(uuid4())))
            connection.execute("INSERT INTO metadata VALUES (?, ?)", ("catalog_version", CATALOG_VERSION))
            connection.execute("INSERT INTO config VALUES (1, 1, ?)", (storage.canonical_json(merged),))
            for problem in PROBLEMS:
                connection.execute("INSERT INTO problems VALUES (?, ?)", (problem["id"], storage.canonical_json(problem)))
            self._seed_policy()
            state = derive_learning_state([], merged, PROBLEMS)
            connection.execute("INSERT INTO learning_state VALUES (1, 0, ?)", (storage.canonical_json(state),))
            connection.execute("COMMIT")
        except BaseException as exc:
            if connection.in_transaction:
                connection.rollback()
            self.close()
            if isinstance(exc, sqlite3.Error):
                raise CoachError("storage_error", "Initialization failed; retry the same local path safely.") from exc
            raise
        return {"initialized": True, "config": self.get_config(), "state_version": 0}

    def _existing_initialization(self, merged: dict, explicit: bool) -> dict:
        """Inputs: requested settings and whether supplied. Outputs: existing status.

        Logic: preserve a completed initialization and reject conflicting settings.
        Dependencies: validated saved configuration and learning state.
        """
        current = self.get_config()
        if explicit and current["config"] != merged:
            raise CoachError("config_conflict", "Existing configuration differs; update it explicitly.")
        return {"initialized": False, "config": current, "state_version": self._state()["state_version"]}

    def get_config(self) -> dict:
        """Inputs: none. Outputs: persisted configuration and its revision.

        Logic: read the single configuration row.
        Dependencies: an initialized database.
        """
        row = self._db().execute("SELECT revision, body FROM config WHERE singleton = 1").fetchone()
        if row is None:
            raise CoachError("unsupported_database", "Configuration is missing.")
        config = storage.decode_object(row["body"], "configuration")
        try:
            normalized = validate_config(config)
        except CoachError as exc:
            raise CoachError("integrity_error", "Stored configuration is invalid.") from exc
        if normalized != config:
            raise CoachError("integrity_error", "Stored configuration is incomplete or not normalized.")
        return {"revision": row["revision"], "config": config}

    def get_workspace_identity(self) -> dict:
        """Read the durable identity without creating or changing learning records.

        Inputs: None. Use this Coach's initialized database.
        Outputs: The saved workspace_id.
        Logic: Read metadata and reject a missing or malformed identity.
        Dependencies: The existing metadata table and CoachError.
        """
        row = self._db().execute("SELECT value FROM metadata WHERE key = 'workspace_id'").fetchone()
        if row is None or not isinstance(row[0], str) or not row[0].strip():
            raise CoachError("integrity_error", "Workspace identity is missing.")
        return {"workspace_id": row[0]}

    def update_config(self, changes: dict, expected_revision: int) -> dict:
        """Inputs: configuration changes and the expected revision. Outputs: new config.

        Logic: reject stale edits, validate all settings, and rebuild derived state.
        Dependencies: pure configuration rules and a SQLite transaction.
        """
        if not isinstance(changes, dict):
            raise CoachError("validation_error", "Configuration changes must be an object.")
        self._revision(expected_revision)
        connection = self._db()
        with storage.transaction(connection):
            current = self.get_config()
            if expected_revision != current["revision"]:
                raise CoachError("revision_conflict", "Configuration changed; reload it first.", {"current_revision": current["revision"]})
            merged = {**current["config"], **changes}
            normalized = validate_config(merged)
            if normalized != current["config"]:
                connection.execute("UPDATE config SET revision = revision + 1, body = ? WHERE singleton = 1", (storage.canonical_json(normalized),))
                changed = {key for key in set(normalized) | set(current["config"])
                           if normalized.get(key) != current["config"].get(key)}
                if not changed <= NON_LEARNING_FIELDS:
                    self._refresh_state()
        return self.get_config()

    def preview_config(self, changes: dict, training_date: str | None = None) -> dict:
        """Inputs: unsaved configuration changes and an optional date. Outputs: a read-only preview.

        Logic: validate the merged settings and run selection without saving or allocating.
        Dependencies: pure configuration rules, the active policy, and the plan report.
        """
        if not isinstance(changes, dict):
            raise CoachError("validation_error", "Configuration changes must be an object.")
        current = self.get_config()
        proposed = validate_config({**current["config"], **changes})
        local_date = self._date(training_date)
        policy = self.get_policy(local_date)
        existing = self._db().execute("SELECT id FROM plans WHERE training_date = ?", (local_date,)).fetchone()
        report = self._policy_report(policy["policy"], local_date, proposed)
        return {"training_date": local_date, "current_revision": current["revision"], "config": proposed,
                "plan_exists": existing is not None, "saved": False, **report}

    def schedule_status(self, observed_rrule: str | None = None, observed_cron: str | None = None,
                        observed_timezone: str | None = None) -> dict:
        """Inputs: an optional observed host rule and timezone. Outputs: schedule data.

        Logic: describe the saved run time, or compare it with an observed host rule.
        Dependencies: saved configuration, workspace identity, and core schedule rules.
        """
        from .core.schedule import check_schedule, describe_schedule

        config = self.get_config()
        settings = config["config"]
        now = datetime.now(timezone.utc)
        if observed_rrule is None and observed_cron is None:
            if observed_timezone is not None:
                raise CoachError("validation_error", "Use --observed-timezone with an observed rule.")
            result = describe_schedule(settings["run_time"], settings["timezone"], now)
        else:
            result = check_schedule(settings["run_time"], settings["timezone"], now,
                                    observed_rrule, observed_cron, observed_timezone)
        return {**result, "config_revision": config["revision"], **self.get_workspace_identity()}

    def _date(self, value: str | None) -> str:
        """Inputs: an optional training date. Outputs: an explicit local date.

        Logic: validate supplied dates or use the configured timezone today.
        Dependencies: saved configuration, ZoneInfo, and the system clock.
        """
        if value is not None:
            return _iso_date(value)
        zone = ZoneInfo(self.get_config()["config"]["timezone"])
        return datetime.now(zone).date().isoformat()

    def _revision(self, value: object) -> int:
        """Inputs: a revision value. Outputs: a non-negative integer.

        Logic: reject booleans and invalid revision numbers.
        Dependencies: CoachError for validation failures.
        """
        if type(value) is not int or value < 0:
            raise CoachError("validation_error", "Expected revision must be a non-negative integer.")
        return value

    def _state(self) -> dict:
        """Inputs: none. Outputs: the persisted learning projection and version.

        Logic: decode the single projection row.
        Dependencies: the learning_state table.
        """
        row = self._db().execute("SELECT version, body FROM learning_state WHERE singleton = 1").fetchone()
        if row is None:
            raise CoachError("unsupported_database", "Learning state is missing.")
        state = storage.decode_object(row["body"], "learning state")
        if not isinstance(state.get("problems"), list) or not isinstance(state.get("topics"), list) or not isinstance(state.get("rule_version"), str):
            raise CoachError("integrity_error", "Stored learning state has an invalid shape.")
        return {**state, "state_version": row["version"]}

    def list_problems(self) -> dict:
        """Inputs: none. Outputs: stored public problem metadata.

        Logic: read the catalog that was pinned when the store was initialized.
        Dependencies: problems and catalog metadata tables.
        """
        rows = self._db().execute("SELECT body FROM problems ORDER BY id").fetchall()
        version = self._db().execute("SELECT value FROM metadata WHERE key = 'catalog_version'").fetchone()[0]
        return {"catalog_version": version, "problems": [storage.decode_object(row[0], "problem metadata") for row in rows]}

    def _new_attempt(self, problem_id: str, language: str, training_date: str, kind: str, source_attempt_id: str | None = None, review_id: str | None = None) -> str:
        """Inputs: problem, language, date, kind, and optional source. Outputs: ID.

        Logic: reserve a single practice unit without claiming it has started.
        Dependencies: the caller's active transaction and attempts table.
        """
        attempt_id = str(uuid4())
        self._db().execute(
            "INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (attempt_id, problem_id, language, kind, training_date, source_attempt_id, review_id, _now()),
        )
        if review_id is not None:
            self._db().execute("UPDATE reviews SET attempt_id = ?, status = 'in_progress' WHERE id = ?", (attempt_id, review_id))
        return attempt_id

    def ensure_plan(self, training_date: str | None = None) -> dict:
        """Inputs: an optional training date. Outputs: a frozen daily plan.

        Logic: reuse an existing plan or select and reserve work under one writer lock.
        Dependencies: saved catalog, pure selection rules, and SQLite transactions.
        """
        local_date = self._date(training_date)
        connection = self._db()
        with storage.transaction(connection):
            exists = connection.execute("SELECT id FROM plans WHERE training_date = ?", (local_date,)).fetchone()
            if exists is not None:
                created = False
            else:
                created = True
                config = self.get_config()
                state = self._state()
                catalog = self.list_problems()
                policy = self.get_policy(local_date)
                report = self._policy_report(policy["policy"], local_date)
                candidates = report["selected"]
                validate_plan_candidates(candidates, catalog["problems"], policy["policy"], config["config"])
                for candidate in candidates:
                    linked_id = candidate.get("attempt_id") or candidate.get("review_source_attempt_id")
                    if linked_id is not None:
                        linked = self._attempt(linked_id)
                        if linked["problem_id"] != candidate["problem_id"] or linked["language"] != config["config"]["language"]:
                            raise CoachError("policy_violation", "A selected practice link does not match its problem and language.")
                if not candidates:
                    reason = "no_eligible_metadata" if report["eligible_count"] == 0 else "no_schedulable_candidates"
                    if report["remaining_capacity"] == 0 and report["capacity_limited_count"] > 0:
                        reason = "daily_capacity_reserved"
                    diagnostics = {**report, "reason": reason}
                    return {"status": "blocked", "created": False, "training_date": local_date, "items": [], "policy_revision": policy["revision"], "policy_snapshot": policy["policy"], "diagnostics": diagnostics}
                plan_id = str(uuid4())
                connection.execute(
                    "INSERT INTO plans (id, training_date, timezone, config_revision, config_snapshot, state_version, catalog_version, rule_version, created_at, policy_revision, policy_snapshot, diagnostics) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (plan_id, local_date, config["config"]["timezone"], config["revision"], storage.canonical_json(config["config"]), state["state_version"], catalog["catalog_version"], state["rule_version"], _now(), policy["revision"], storage.canonical_json(policy["policy"]), storage.canonical_json(report)),
                )
                for position, candidate in enumerate(candidates, 1):
                    attempt_id = candidate.get("attempt_id")
                    if attempt_id is None:
                        source = candidate.get("review_source_attempt_id")
                        review = None
                        if source:
                            review = connection.execute("SELECT id, attempt_id FROM reviews WHERE source_attempt_id = ?", (source,)).fetchone()
                        existing_attempt = self._attempt(review["attempt_id"]) if review is not None and review["attempt_id"] else None
                        if existing_attempt is not None and (existing_attempt["feedback"] or {}).get("result") in (None, "D", "E"):
                            attempt_id = existing_attempt["id"]
                        else:
                            attempt_id = self._new_attempt(candidate["problem_id"], config["config"]["language"], local_date, "review" if source else "practice", source, review["id"] if review else None)
                    connection.execute("INSERT INTO plan_items VALUES (?, ?, ?, ?)", (plan_id, position, attempt_id, candidate["reason"]))
                    context = candidate.get("training_context")
                    if config["config"].get("training_profile") == "tokyo-interview-v1":
                        context = {key: value for key, value in candidate.items()
                                   if key not in {"problem_id", "attempt_id", "review_source_attempt_id"}}
                        context.setdefault("original_recommendation_date", local_date)
                    if context:
                        connection.execute("INSERT INTO training_contexts(problem_id, attempt_id, body, created_at) VALUES (?, ?, ?, ?)",
                                           (candidate["problem_id"], attempt_id, storage.canonical_json(context), _now()))
                maximum = self._daily_maximum(policy["policy"])
                if maximum is not None and len(self._reserved_attempt_ids(local_date)) > maximum:
                    raise CoachError("policy_violation", "Publishing this plan would exceed reserved daily capacity.")
        return {**self.get_plan(local_date), "created": created}

    def get_plan(self, training_date: str | None = None) -> dict:
        """Inputs: an optional training date. Outputs: a saved plan and current feedback.

        Logic: keep plan membership fixed while resolving current attempt revisions.
        Dependencies: plans, plan_items, attempts, and saved catalog metadata.
        """
        local_date = self._date(training_date)
        row = self._db().execute("SELECT * FROM plans WHERE training_date = ?", (local_date,)).fetchone()
        if row is None:
            raise CoachError("not_found", "No plan exists for this training date.")
        plan = dict(row)
        plan["config_snapshot"] = storage.decode_object(plan["config_snapshot"], "plan configuration")
        plan["policy_snapshot"] = storage.decode_object(plan["policy_snapshot"], "plan policy")
        plan["diagnostics"] = storage.decode_object(plan["diagnostics"], "plan diagnostics")
        attempts = {attempt["id"]: attempt for attempt in self._attempts()}
        problems = {problem["id"]: problem for problem in self.list_problems()["problems"]}
        plan["items"] = []
        for item in self._db().execute("SELECT * FROM plan_items WHERE plan_id = ? ORDER BY position", (plan["id"],)):
            attempt = attempts[item["attempt_id"]]
            plan["items"].append({"position": item["position"], "reason": item["reason"], "attempt_id": attempt["id"], "problem": problems[attempt["problem_id"]], "attempt": attempt})
        current_policy = self.get_policy(local_date)
        conflicts = []
        for item in plan["items"]:
            check = eligibility(item["problem"], current_policy["policy"])
            if not check["allowed"]:
                conflicts.append({"attempt_id": item["attempt_id"], "problem_id": item["problem"]["id"], "reasons": check["reasons"]})
        maximum = current_policy["policy"]["max_daily_count"]
        if maximum is not None and len(plan["items"]) > maximum:
            conflicts.append({"reasons": ["max_daily_count_exceeded"], "count": len(plan["items"]), "limit": maximum})
        plan["current_policy"] = current_policy
        plan["current_policy_match"] = not conflicts
        plan["current_policy_conflicts"] = conflicts
        return plan

    def _hash(self, payload: dict) -> str:
        """Inputs: a request payload. Outputs: its stable SHA-256 digest.

        Logic: hash canonical JSON so object key order does not affect retries.
        Dependencies: hashlib and canonical_json.
        """
        return hashlib.sha256(storage.canonical_json(payload).encode("utf-8")).hexdigest()

    def _replay(self, submission_id: str, payload_hash: str) -> dict | None:
        """Inputs: a submission ID and digest. Outputs: the original receipt or none.

        Logic: reject reused IDs with different content before checking versions.
        Dependencies: permanent immutable submission receipts.
        """
        row = self._db().execute("SELECT payload_hash, receipt FROM submissions WHERE id = ?", (submission_id,)).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != payload_hash:
            raise CoachError("idempotency_conflict", "This submission ID belongs to different content.")
        return storage.decode_object(row["receipt"], "submission receipt")

    def submit_feedback(self, attempt_id: str, submission_id: str, expected_revision: int, changes: dict, kind: str = "progress", occurred_at: str | None = None) -> dict:
        """Inputs: target, stable submission ID, version, field changes, kind, time.
        Outputs: a persisted receipt for the applied revision.

        Logic: append history, rebuild state, and save a receipt in one transaction.
        Dependencies: feedback rules, permanent deduplication, and SQLite storage.
        """
        _identifier(attempt_id, "Attempt ID")
        _identifier(submission_id, "Submission ID")
        self._revision(expected_revision)
        if not isinstance(changes, dict) or not changes:
            raise CoachError("validation_error", "Feedback changes must be a non-empty object.")
        if kind not in ("progress", "correction"):
            raise CoachError("validation_error", "Feedback kind must be progress or correction.")
        normalized_time = _timestamp(occurred_at) if occurred_at is not None else None
        payload_hash = self._hash({"operation": "submit_feedback", "attempt_id": attempt_id, "expected_revision": expected_revision, "changes": changes, "kind": kind, "occurred_at": normalized_time})
        connection = self._db()
        with storage.transaction(connection):
            replay = self._replay(submission_id, payload_hash)
            if replay is not None:
                return replay
            attempt = self._attempt(attempt_id)
            if expected_revision != attempt["revision"]:
                raise CoachError("revision_conflict", "Feedback changed; reload the attempt first.", {"current_revision": attempt["revision"], "feedback": attempt["feedback"]})
            snapshot = merge_feedback(attempt["feedback"], changes, kind)
            received_at = _now()
            same_result = attempt["feedback"] is not None and snapshot.get("result") == attempt["feedback"].get("result")
            preserve_time = attempt["revision"] > 0 and normalized_time is None and (kind == "correction" or same_result)
            effective_time = attempt["occurred_at"] if preserve_time else normalized_time or received_at
            if preserve_time:
                practice_date = attempt["practice_date"]
            else:
                zone = ZoneInfo(self.get_config()["config"]["timezone"])
                practice_date = datetime.fromisoformat(effective_time).astimezone(zone).date().isoformat()
            revision = attempt["revision"] + 1
            connection.execute(
                "INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (attempt_id, revision, submission_id, kind, storage.canonical_json(changes), storage.canonical_json(snapshot), practice_date, effective_time, received_at),
            )
            state = self._refresh_state()
            receipt = {"submission_id": submission_id, "operation": "submit_feedback", "attempt_id": attempt_id, "revision": revision, "payload_hash": payload_hash, "state_version": state["state_version"], "status": "applied", "saved_at": received_at}
            connection.execute("INSERT INTO submissions VALUES (?, ?, ?, ?)", (submission_id, "submit_feedback", payload_hash, storage.canonical_json(receipt)))
        return self.receipt(submission_id)

    def receipt(self, submission_id: str) -> dict:
        """Inputs: a stable submission ID. Outputs: its committed receipt.

        Logic: read back permanent acknowledgement data after commit.
        Dependencies: the submissions table.
        """
        _identifier(submission_id, "Submission ID")
        row = self._db().execute("SELECT receipt FROM submissions WHERE id = ?", (submission_id,)).fetchone()
        if row is None:
            raise CoachError("not_found", "No committed receipt exists for this submission.")
        return storage.decode_object(row[0], "submission receipt")

    def _refresh_state(self) -> dict:
        """Inputs: none. Outputs: the new learning state and version.

        Logic: derive evidence once per attempt and reconcile traceable review tasks.
        Dependencies: the caller's write transaction, pure rules, and current attempts.
        """
        connection = self._db()
        attempts = self._attempts()
        state = derive_learning_state(attempts, self.get_config()["config"], self.list_problems()["problems"])
        connection.execute("UPDATE learning_state SET version = version + 1, body = ? WHERE singleton = 1", (storage.canonical_json(state),))
        lookup = {attempt["id"]: attempt for attempt in attempts}
        for row in connection.execute("SELECT id, attempt_id FROM reviews").fetchall():
            executing = lookup.get(row["attempt_id"])
            if executing is None:
                status = "superseded"
            else:
                result = (executing["feedback"] or {}).get("result")
                if result in ("A", "B", "C"):
                    status = "completed"
                elif result == "F":
                    status = "cancelled"
                else:
                    status = "in_progress"
            connection.execute("UPDATE reviews SET status = ? WHERE id = ?", (status, row["id"]))
        for problem in state["problems"]:
            source = problem.get("review_source_attempt_id")
            due_date = problem.get("review_due")
            if source is None or due_date is None:
                continue
            existing = connection.execute("SELECT id, attempt_id FROM reviews WHERE source_attempt_id = ?", (source,)).fetchone()
            if existing is None:
                connection.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, ?, 'pending', NULL)", (str(uuid4()), source, problem["problem_id"], problem["language"], due_date))
            elif existing["attempt_id"] is None:
                connection.execute("UPDATE reviews SET due_date = ?, status = 'pending' WHERE id = ?", (due_date, existing["id"]))
            else:
                connection.execute("UPDATE reviews SET due_date = ? WHERE id = ?", (due_date, existing["id"]))
        return self._state()

    def learning_state(self) -> dict:
        """Inputs: none. Outputs: evidence, review tasks, and unresolved work.

        Logic: expose saved derived state alongside current practice records.
        Dependencies: the learning projection, review table, and attempts.
        """
        state = self._state()
        state["reviews"] = [dict(row) for row in self._db().execute("SELECT * FROM reviews ORDER BY due_date, id")]
        state["attempts"] = self._attempts()
        policy = self.get_policy()
        state["policy_paused"] = {"training_date": policy["training_date"], "policy_revision": policy["revision"], **self._paused_by_policy(policy["policy"], policy["training_date"])}
        return state

    def start_practice(self, problem_id: str, submission_id: str, language: str | None = None, review_id: str | None = None, training_date: str | None = None) -> dict:
        """Inputs: problem, stable operation ID, and optional practice context.
        Outputs: a committed receipt and the reserved attempt identifier.

        Logic: create an explicit new practice or claim one pending review idempotently.
        Dependencies: stored catalog, configuration validation, and SQLite transactions.
        """
        _identifier(problem_id, "Problem ID")
        _identifier(submission_id, "Submission ID")
        if review_id is not None:
            _identifier(review_id, "Review ID")
        payload_hash = self._hash({"operation": "start_practice", "problem_id": problem_id, "language": language, "review_id": review_id, "training_date": training_date})
        connection = self._db()
        with storage.transaction(connection):
            replay = self._replay(submission_id, payload_hash)
            if replay is not None:
                return replay
            config = self.get_config()["config"]
            selected_language = language or config["language"]
            validate_config({**config, "language": selected_language})
            selected_date = self._date(training_date)
            if connection.execute("SELECT id FROM problems WHERE id = ?", (problem_id,)).fetchone() is None:
                raise CoachError("not_found", "The problem is not in the local catalog.")
            policy = self.get_policy(selected_date)
            problem = next(item for item in self.list_problems()["problems"] if item["id"] == problem_id)
            check = eligibility(problem, policy["policy"])
            if not check["allowed"]:
                raise CoachError("policy_violation", "The current policy excludes this practice.", {"problem_id": problem_id, "reasons": check["reasons"]})
            maximum = self._daily_maximum(policy["policy"])
            if maximum is not None:
                reserved = self._reserved_attempt_ids(selected_date)
                if len(reserved) >= maximum:
                    raise CoachError("daily_capacity_exceeded", "The policy's daily practice capacity is already reserved.", {"reserved_count": len(reserved), "limit": maximum})
            profile_context = None
            if config.get("training_profile") == "tokyo-interview-v1":
                from .core.training_profile import primary_framework, validate_score, verified_sources

                profile_context = self._selection_context(selected_date)["candidates"].get(problem_id, {})
                frame = primary_framework(problem, context=profile_context)
                if frame is None or not verified_sources(profile_context) or validate_score(profile_context.get("score")) is None:
                    raise CoachError("training_evidence_required", "Manual practice needs researched source, score, and framework context.")
                all_attempts = {item["id"]: item for item in self._attempts()}
                for reserved_id in self._reserved_attempt_ids(selected_date):
                    reserved_attempt = all_attempts[reserved_id]
                    reserved_problem = next(item for item in self.list_problems()["problems"] if item["id"] == reserved_attempt["problem_id"])
                    if reserved_attempt["problem_id"] == problem_id or primary_framework(reserved_problem, reserved_attempt) == frame:
                        raise CoachError("daily_framework_conflict", "This problem or primary framework is already allocated today.")
            source = None
            if review_id is not None:
                review = connection.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
                if review is None or review["problem_id"] != problem_id or review["language"] != selected_language:
                    raise CoachError("not_found", "No matching review task exists.")
                if review["status"] != "pending" or review["attempt_id"] is not None:
                    raise CoachError("review_conflict", "The review has already been claimed or closed.")
                source = review["source_attempt_id"]
            attempt_id = self._new_attempt(problem_id, selected_language, selected_date, "review" if source else "redo", source, review_id)
            if profile_context is not None:
                from .core.training_profile import timebox

                practiced = any(item["problem_id"] == problem_id and item["id"] != attempt_id and item.get("feedback")
                                for item in self._attempts())
                identity = "retest" if source or practiced else "new"
                context = {**profile_context, "training_identity": identity, "original_recommendation_date": selected_date,
                           "timebox": timebox(identity)}
                connection.execute("INSERT INTO training_contexts(problem_id, attempt_id, body, created_at) VALUES (?, ?, ?, ?)",
                                   (problem_id, attempt_id, storage.canonical_json(context), _now()))
            receipt = {"submission_id": submission_id, "operation": "start_practice", "attempt_id": attempt_id, "revision": 0, "payload_hash": payload_hash, "state_version": self._state()["state_version"], "status": "applied", "saved_at": _now()}
            connection.execute("INSERT INTO submissions VALUES (?, ?, ?, ?)", (submission_id, "start_practice", payload_hash, storage.canonical_json(receipt)))
        return self.receipt(submission_id)

    def rebuild_state(self) -> dict:
        """Inputs: none. Outputs: rebuilt learning state and provenance.

        Logic: recompute projections from immutable feedback without editing plans.
        Dependencies: current deterministic rules and one SQLite transaction.
        """
        with storage.transaction(self._db()):
            self._refresh_state()
        return self.learning_state()

    def integrity_check(self) -> dict:
        """Inputs: none. Outputs: database, schema, and foreign-key check results.

        Logic: verify SQLite pages, supported metadata, and referential integrity.
        Dependencies: SQLite integrity pragmas and storage schema checks.
        """
        connection = self._db()
        storage.check_schema(connection)
        pages = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        foreign_keys = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
        if pages != ["ok"] or foreign_keys:
            raise CoachError("integrity_error", "Database integrity checks failed.", {"integrity": pages, "foreign_keys": foreign_keys})
        self.get_config()
        self._state()
        self.list_problems()
        self._attempts()
        for table, column in (("feedback", "changes"), ("feedback", "snapshot"), ("submissions", "receipt"), ("plans", "config_snapshot"), ("plans", "policy_snapshot"), ("plans", "diagnostics")):
            for row in connection.execute(f"SELECT {column} FROM {table}"):
                storage.decode_object(row[0], f"{table}.{column}")
        self.policy_history()
        return {"status": "ok", "schema_version": storage.SCHEMA_VERSION, "integrity": pages, "foreign_keys": foreign_keys}

    def backup(self, destination: Path) -> dict:
        """Inputs: a new backup path. Outputs: verified backup metadata.

        Logic: reserve a private file, use SQLite backup, verify, and never overwrite.
        Dependencies: SQLite's online backup API and local filesystem permissions.
        """
        destination = Path(destination).expanduser()
        if destination.exists() or destination.is_symlink():
            raise CoachError("already_exists", "The backup destination already exists.")
        source = self._db()
        version = source.execute("PRAGMA user_version").fetchone()[0]
        physical = [row[0] for row in source.execute("PRAGMA integrity_check")]
        foreign = list(source.execute("PRAGMA foreign_key_check"))
        if physical != ["ok"] or foreign:
            raise CoachError("integrity_error", "The source database failed backup checks.")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        target = sqlite3.connect(str(destination), isolation_level=None)
        try:
            source.backup(target)
            storage.check_schema(target)
            integrity = [row[0] for row in target.execute("PRAGMA integrity_check")]
            foreign_keys = list(target.execute("PRAGMA foreign_key_check"))
            if integrity != ["ok"] or foreign_keys:
                raise CoachError("integrity_error", "Backup verification failed.")
        except BaseException:
            target.close()
            destination.unlink(missing_ok=True)
            raise
        target.close()
        state_version = source.execute("SELECT version FROM learning_state WHERE singleton = 1").fetchone()[0]
        return {"status": "verified", "schema_version": version, "state_version": state_version}

    def _read_derived(self, language: str | None, derive) -> dict:
        """Read one derived view from a consistent authority snapshot.

        Inputs: An optional language and a pure derivation function.
        Outputs: The derived data with the matching state version.
        Logic: Read evidence and mastery in one read transaction without saving.
        Dependencies: A deferred read transaction, stored catalog, and the derivation.
        """
        connection = self._db()
        owns_snapshot = not connection.in_transaction
        if owns_snapshot:
            connection.execute("BEGIN")
        try:
            config = self.get_config()["config"]
            selected_language = config["language"] if language is None else validate_config({**config, "language": language})["language"]
            state = self._state()
            derived = derive(self._attempts(), self.list_problems()["problems"], selected_language, state["problems"])
            result = {**derived, "state_version": state["state_version"]}
            if owns_snapshot:
                connection.commit()
            return result
        except BaseException:
            if owns_snapshot:
                connection.rollback()
            raise

    def get_topic_scores(self, language: str | None = None) -> dict:
        """Read topic rates from one consistent authority snapshot.

        Inputs: An optional language; None uses the saved default language.
        Outputs: Self-reported topic metrics and the matching state version.
        Logic: Read existing evidence and mastery without rebuilding or saving scores.
        Dependencies: _read_derived and derive_topic_scores.
        """
        return self._read_derived(language, derive_topic_scores)

    def get_practice_progress(self, language: str | None = None) -> dict:
        """Read daily activity and per-problem results from one snapshot.

        Inputs: An optional language; None uses the saved default language.
        Outputs: Self-reported daily counts, problem rows, and the state version.
        Logic: Derive read-only progress without changing plans or mastery.
        Dependencies: _read_derived and derive_practice_progress.
        """
        return self._read_derived(language, derive_practice_progress)
