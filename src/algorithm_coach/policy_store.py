"""Persist local policies and safely preview or append catalog metadata."""

from datetime import date, datetime, timedelta, timezone
import re
from uuid import uuid4

from .catalog_validation import CATALOG_METADATA_FIELDS, validate_catalog
from .errors import CoachError
from .policies import default_policy, eligibility, filter_catalog, policy_active, validate_plan_candidates, validate_policy
from .rules import select_candidates
from . import storage


def _now() -> str:
    """Inputs: none. Outputs: a UTC timestamp.

    Logic: read the system clock with microsecond precision.
    Dependencies: datetime and the operating system clock.
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _text(value: object, label: str) -> str:
    """Inputs: a value and label. Outputs: bounded non-empty text.

    Logic: reject invalid identifiers before a write transaction.
    Dependencies: CoachError.
    """
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise CoachError("validation_error", f"{label} must be non-empty text of at most 200 characters.")
    return value


class PolicyMixin:
    """Add policy use cases to the shared local Coach service."""

    def _seed_policy(self) -> None:
        """Inputs: none. Outputs: none.

        Logic: persist the unrestricted baseline in the current transaction.
        Dependencies: the host service connection and canonical hashing.
        """
        body = validate_policy(default_policy(), self.list_problems()["problems"])
        self._db().execute("INSERT INTO policies VALUES (0, NULL, ?, ?, ?)", (storage.canonical_json(body), self._hash(body), _now()))

    def _policy_records(self) -> list[dict]:
        """Inputs: none. Outputs: validated immutable activation records.

        Logic: validate all stored bodies and hashes so corruption cannot fall back.
        Dependencies: saved catalog metadata and domain policy validation.
        """
        catalog = self.list_problems()["problems"]
        result = []
        for row in self._db().execute("SELECT * FROM policies ORDER BY revision"):
            record = dict(row)
            body = storage.decode_object(record.pop("body"), "policy")
            try:
                normalized = validate_policy(body, catalog)
            except CoachError as exc:
                raise CoachError("integrity_error", "A saved policy is invalid; no fallback was applied.") from exc
            if normalized != body or self._hash(body) != record["content_hash"]:
                raise CoachError("integrity_error", "A saved policy failed content verification.")
            result.append({**record, "policy": body})
        if not result or result[0]["revision"] != 0:
            raise CoachError("integrity_error", "The baseline policy is missing.")
        return result

    def get_policy(self, training_date: str | None = None) -> dict:
        """Inputs: an optional date. Outputs: effective policy and latest CAS revision.

        Logic: resolve the highest matching activation, with explicit dated fallback.
        Dependencies: validated activation history and configured training dates.
        """
        local_date = self._date(training_date)
        records = self._policy_records()
        matching = [record for record in records if policy_active(record["policy"], local_date)]
        if not matching:
            raise CoachError("integrity_error", "The baseline policy does not cover the requested date.")
        effective = matching[-1]
        latest = records[-1]
        fallback = effective["revision"] != latest["revision"]
        reason = None
        if fallback:
            if latest["policy"]["effective_from"] > local_date:
                reason = "not_yet_effective"
            elif latest["policy"]["effective_until"] is not None and latest["policy"]["effective_until"] < local_date:
                reason = "expired"
            else:
                reason = "no_active_revision"
        return {"training_date": local_date, "revision": effective["revision"], "latest_revision": latest["revision"], "policy": effective["policy"], "content_hash": effective["content_hash"], "fallback": fallback, "fallback_reason": reason}

    def _proposal(self, proposal_id: str) -> dict:
        """Inputs: a proposal ID. Outputs: the immutable, verified proposal.

        Logic: reject missing proposals and altered saved content.
        Dependencies: policy_proposals, saved catalog, and domain validation.
        """
        _text(proposal_id, "Proposal ID")
        row = self._db().execute("SELECT * FROM policy_proposals WHERE id = ?", (proposal_id,)).fetchone()
        if row is None:
            raise CoachError("not_found", "The policy proposal does not exist.")
        proposal = dict(row)
        body = storage.decode_object(proposal["body"], "policy proposal")
        try:
            normalized = validate_policy(body, self.list_problems()["problems"])
        except CoachError as exc:
            raise CoachError("integrity_error", "The saved policy proposal is invalid.") from exc
        if normalized != body or self._hash(body) != proposal["content_hash"]:
            raise CoachError("integrity_error", "The saved policy proposal failed content verification.")
        proposal["body"] = body
        return proposal

    def policy_history(self) -> dict:
        """Inputs: none. Outputs: immutable proposals and activation history.

        Logic: decode all records without changing their activation state.
        Dependencies: validated proposal and policy readers.
        """
        policies = self._policy_records()
        proposals = [self._proposal(row[0]) for row in self._db().execute("SELECT id FROM policy_proposals ORDER BY created_at, id")]
        return {"latest_revision": policies[-1]["revision"], "policies": policies, "proposals": proposals}

    def propose_policy(self, changes: dict, expected_revision: int, submission_id: str) -> dict:
        """Inputs: scope changes, latest revision, and a stable operation ID.
        Outputs: a committed proposal receipt containing the full bound content.

        Logic: overlay dated effective scope and bind config, catalog, and policy versions.
        Dependencies: domain validation and one immutable SQLite transaction.
        """
        _text(submission_id, "Submission ID")
        self._revision(expected_revision)
        if not isinstance(changes, dict) or not changes:
            raise CoachError("validation_error", "Policy changes must be a non-empty object.")
        payload_hash = self._hash({"operation": "propose_policy", "changes": changes, "expected_revision": expected_revision})
        with storage.transaction(self._db()):
            replay = self._replay(submission_id, payload_hash)
            if replay is not None:
                return replay
            config = self.get_config()
            catalog = self.list_problems()
            if "effective_from" in changes:
                if changes["effective_from"] is None:
                    raise CoachError("validation_error", "effective_from must be an explicit date, not null.")
                start = self._date(changes["effective_from"])
            else:
                try:
                    start = (date.fromisoformat(self._date(None)) + timedelta(days=1)).isoformat()
                except OverflowError as exc:
                    raise CoachError("validation_error", "The default next training date is outside the supported range.") from exc
            current = self.get_policy(start)
            if current["latest_revision"] != expected_revision:
                raise CoachError("revision_conflict", "Policy activation history changed; read it again.", {"current_revision": current["latest_revision"]})
            body = {**current["policy"], **changes, "effective_from": start, "effective_until": changes.get("effective_until")}
            body = validate_policy(body, catalog["problems"])
            content_hash = self._hash(body)
            proposal_id = str(uuid4())
            created_at = _now()
            self._db().execute("INSERT INTO policy_proposals VALUES (?, ?, ?, ?, ?, ?, ?)", (proposal_id, storage.canonical_json(body), content_hash, expected_revision, config["revision"], catalog["catalog_version"], created_at))
            receipt = {"submission_id": submission_id, "operation": "propose_policy", "proposal_id": proposal_id, "body": body, "content_hash": content_hash, "base_revision": expected_revision, "config_revision": config["revision"], "catalog_version": catalog["catalog_version"], "status": "proposed", "saved_at": created_at, "payload_hash": payload_hash}
            self._db().execute("INSERT INTO submissions VALUES (?, ?, ?, ?)", (submission_id, "propose_policy", payload_hash, storage.canonical_json(receipt)))
        return self.receipt(submission_id)

    def _paused_by_policy(self, body: dict, training_date: str) -> dict:
        """Inputs: policy content and date. Outputs: paused unfinished work and reviews.

        Logic: report exclusions without changing attempts or inventing feedback.
        Dependencies: saved metadata, current attempts, and review tasks.
        """
        catalog = {problem["id"]: problem for problem in self.list_problems()["problems"]}
        language = self.get_config()["config"]["language"]
        attempts = self._attempts()
        lookup = {attempt["id"]: attempt for attempt in attempts}
        backlog = []
        for attempt in attempts:
            feedback = attempt["feedback"] or {}
            result = feedback.get("result")
            due_defer = result == "E" and feedback.get("defer_until") is not None and feedback["defer_until"] <= training_date
            if attempt["language"] != language or attempt["planned_date"] > training_date or (result not in (None, "D") and not due_defer):
                continue
            check = eligibility(catalog[attempt["problem_id"]], body)
            if not check["allowed"]:
                backlog.append({"attempt_id": attempt["id"], "problem_id": attempt["problem_id"], "reasons": check["reasons"]})
        reviews = []
        for row in self._db().execute("SELECT * FROM reviews WHERE status IN ('pending', 'in_progress') ORDER BY due_date, id"):
            if row["language"] != language:
                continue
            executing = lookup.get(row["attempt_id"])
            if executing is not None:
                feedback = executing["feedback"] or {}
                result = feedback.get("result")
                if result == "F" or (result == "E" and (feedback.get("defer_until") is None or feedback["defer_until"] > training_date)):
                    continue
            check = eligibility(catalog[row["problem_id"]], body)
            if not check["allowed"]:
                reviews.append({"review_id": row["id"], "attempt_id": row["attempt_id"], "problem_id": row["problem_id"], "due_date": row["due_date"], "reasons": check["reasons"]})
        return {"backlog": backlog, "reviews": reviews}

    def _reserved_attempt_ids(self, training_date: str) -> set[str]:
        """Inputs: an explicit training date. Outputs: all reserved practice IDs.

        Logic: count the union of dated reservations and frozen plan references.
        Dependencies: attempts, plan_items, and plans; all scopes share the daily cap.
        """
        connection = self._db()
        reserved = {row[0] for row in connection.execute("SELECT id FROM attempts WHERE planned_date = ?", (training_date,))}
        reserved.update(row[0] for row in connection.execute("SELECT i.attempt_id FROM plan_items i JOIN plans p ON p.id = i.plan_id WHERE p.training_date = ?", (training_date,)))
        return reserved

    def _policy_report(self, body: dict, training_date: str) -> dict:
        """Inputs: policy body and date. Outputs: a read-only scheduling preview.

        Logic: select within all hard gates and report capacity and paused work.
        Dependencies: pure selection, final validation, and persisted training state.
        """
        config = self.get_config()["config"]
        catalog = self.list_problems()["problems"]
        candidates = select_candidates(catalog, self._attempts(), config, training_date, self._state(), body)
        validate_plan_candidates(candidates, catalog, body, config)
        reserved = self._reserved_attempt_ids(training_date)
        maximum = body["max_daily_count"]
        remaining = max(0, maximum - len(reserved)) if maximum is not None else None
        selected = []
        capacity_limited = 0
        for candidate in candidates:
            cost = 0 if candidate.get("attempt_id") in reserved else 1
            if remaining is not None and cost > remaining:
                capacity_limited += 1
                continue
            selected.append(candidate)
            if remaining is not None:
                remaining -= cost
        validate_plan_candidates(selected, catalog, body, config)
        target = min(config["daily_count"], body["max_daily_count"] or config["daily_count"])
        paused = self._paused_by_policy(body, training_date)
        return {"eligible_count": len(filter_catalog(catalog, body)), "selected": selected, "selected_count": len(selected), "target_count": target, "shortfall": max(0, target - len(selected)), "reserved_count": len(reserved), "remaining_capacity": remaining, "capacity_limited_count": capacity_limited, "paused_backlog": paused["backlog"], "paused_reviews": paused["reviews"]}

    def preview_policy(self, proposal_id: str, training_date: str | None = None) -> dict:
        """Inputs: a proposal ID and optional date. Outputs: preview, diff, and staleness.

        Logic: read only; never reserve attempts or freeze a plan.
        Dependencies: validated proposal, current versions, and pure scheduling rules.
        """
        proposal = self._proposal(proposal_id)
        local_date = self._date(proposal["body"]["effective_from"] if training_date is None else training_date)
        if not policy_active(proposal["body"], local_date):
            raise CoachError("inactive_policy", "Preview date falls outside the proposed policy period.")
        current = self.get_policy(local_date)
        config = self.get_config()
        catalog = self.list_problems()
        versions = {"policy_revision": proposal["base_revision"], "config_revision": proposal["config_revision"], "catalog_version": proposal["catalog_version"]}
        stale = current["latest_revision"] != proposal["base_revision"] or config["revision"] != proposal["config_revision"] or catalog["catalog_version"] != proposal["catalog_version"]
        diff = {key: {"before": current["policy"].get(key), "after": value} for key, value in proposal["body"].items() if current["policy"].get(key) != value}
        expiry_fallback = None
        if proposal["body"]["effective_until"] is not None:
            try:
                after = (date.fromisoformat(proposal["body"]["effective_until"]) + timedelta(days=1)).isoformat()
            except OverflowError:
                expiry_fallback = {"available": False, "reason": "outside_supported_date_range"}
            else:
                expiry_fallback = self.get_policy(after)
        report = self._policy_report(proposal["body"], local_date)
        blockers = []
        if stale:
            blockers.append({"code": "stale_proposal", "message": "The proposal's policy, configuration, or catalog binding changed; propose again.", "details": {"base_versions": versions}})
        if report["eligible_count"] == 0:
            blockers.append({"code": "empty_scope", "message": "No stored problem metadata matches this policy.", "details": {"eligible_count": 0}})
        try:
            self._check_frozen_plans(proposal["body"])
        except CoachError as exc:
            if exc.code != "plan_conflict":
                raise
            blockers.append(exc.as_dict())
        return {"proposal_id": proposal_id, "training_date": local_date, "policy": proposal["body"], "content_hash": proposal["content_hash"], "base_versions": versions, "diff": diff, "stale": stale, "expiry_fallback": expiry_fallback, "activation_blockers": blockers, "activation_allowed": not blockers, **report}

    def _check_frozen_plans(self, body: dict) -> None:
        """Inputs: proposed policy body. Outputs: none, or a plan conflict.

        Logic: reject incompatible frozen dates without modifying membership.
        Dependencies: saved plans, metadata, and the final candidate validator.
        """
        catalog = self.list_problems()["problems"]
        conflicts = []
        for row in self._db().execute("SELECT id, training_date, config_snapshot FROM plans WHERE training_date >= ? ORDER BY training_date", (body["effective_from"],)):
            if not policy_active(body, row["training_date"]):
                continue
            config = storage.decode_object(row["config_snapshot"], "frozen plan configuration")
            candidates = []
            for item in self._db().execute("SELECT a.problem_id, a.id AS attempt_id FROM plan_items p JOIN attempts a ON a.id = p.attempt_id WHERE p.plan_id = ? ORDER BY p.position", (row["id"],)):
                candidates.append(dict(item))
            try:
                validate_plan_candidates(candidates, catalog, body, config)
            except CoachError as exc:
                conflicts.append({"plan_id": row["id"], "training_date": row["training_date"], "reason": exc.message, "details": exc.details})
        maximum = body["max_daily_count"]
        if maximum is not None:
            dates = {row[0] for row in self._db().execute("SELECT DISTINCT planned_date FROM attempts WHERE planned_date >= ?", (body["effective_from"],))}
            dates.update(row[0] for row in self._db().execute("SELECT training_date FROM plans WHERE training_date >= ?", (body["effective_from"],)))
            for training_date in sorted(dates):
                if policy_active(body, training_date):
                    count = len(self._reserved_attempt_ids(training_date))
                    if count > maximum:
                        conflicts.append({"training_date": training_date, "reason": "Existing practice reservations exceed the proposed daily cap.", "reserved_count": count, "limit": maximum})
        if conflicts:
            raise CoachError("plan_conflict", "Choose the next unpublished date; existing future plans conflict with this policy.", {"plans": conflicts})

    def activate_policy(self, proposal_id: str, expected_revision: int, content_hash: str, submission_id: str) -> dict:
        """Inputs: exact proposal, latest revision, confirmed hash, and operation ID.
        Outputs: an immutable activation receipt.

        Logic: replay first, then enforce hash, version bindings, scope, and plan safety.
        Dependencies: a SQLite write transaction and validated proposal content.
        """
        _text(proposal_id, "Proposal ID")
        _text(content_hash, "Content hash")
        _text(submission_id, "Submission ID")
        self._revision(expected_revision)
        payload_hash = self._hash({"operation": "activate_policy", "proposal_id": proposal_id, "expected_revision": expected_revision, "content_hash": content_hash})
        with storage.transaction(self._db()):
            replay = self._replay(submission_id, payload_hash)
            if replay is not None:
                return replay
            proposal = self._proposal(proposal_id)
            if proposal["content_hash"] != content_hash:
                raise CoachError("content_mismatch", "Confirm the exact proposal content hash before activation.")
            current = self.get_policy(proposal["body"]["effective_from"])
            if current["latest_revision"] != expected_revision:
                raise CoachError("revision_conflict", "Policy activation history changed; read it again.", {"current_revision": current["latest_revision"]})
            if proposal["base_revision"] != expected_revision or proposal["config_revision"] != self.get_config()["revision"] or proposal["catalog_version"] != self.list_problems()["catalog_version"]:
                raise CoachError("stale_proposal", "The proposal's policy, configuration, or catalog binding changed; propose again.")
            if not filter_catalog(self.list_problems()["problems"], proposal["body"]):
                raise CoachError("empty_scope", "No stored problem metadata matches this policy; import metadata or change the scope.")
            self._check_frozen_plans(proposal["body"])
            revision = expected_revision + 1
            activated_at = _now()
            self._db().execute("INSERT INTO policies VALUES (?, ?, ?, ?, ?)", (revision, proposal_id, storage.canonical_json(proposal["body"]), content_hash, activated_at))
            receipt = {"submission_id": submission_id, "operation": "activate_policy", "proposal_id": proposal_id, "revision": revision, "content_hash": content_hash, "status": "applied", "saved_at": activated_at, "payload_hash": payload_hash}
            self._db().execute("INSERT INTO submissions VALUES (?, ?, ?, ?)", (submission_id, "activate_policy", payload_hash, storage.canonical_json(receipt)))
        return self.receipt(submission_id)

    def policy_capabilities(self) -> dict:
        """Inputs: none. Outputs: policy fields and available metadata coverage.

        Logic: report current known topics, difficulties, and problems without fetching URLs.
        Dependencies: the append-only local catalog and policy defaults.
        """
        catalog = self.list_problems()
        topics = sorted({tag for problem in catalog["problems"] for tag in problem["tags"]})
        difficulties = sorted({problem["difficulty"] for problem in catalog["problems"]})
        return {"fields": list(default_policy()), "topics": topics, "difficulties": difficulties, "problem_ids": [problem["id"] for problem in catalog["problems"]], "catalog_version": catalog["catalog_version"], "problem_count": len(catalog["problems"]), "supports": {"hard_scope": True, "preferred_topics": True, "max_daily_count": True, "dated_policy": True, "metadata_import": True, "metadata_import_preview": True, "metadata_import_hash_guard": True, "problem_statement_import": False, "remote_fetch": False}}

    def preview_catalog(self, problems: list[dict]) -> dict:
        """Classify one metadata batch without changing local training records.

        Inputs: A non-empty list of five-field problem metadata objects.
        Outputs: Normalized content, new and identical entries, conflicts, and a hash.
        Logic: Validate format, then compare every ID in one deferred read snapshot.
        Dependencies: validate_catalog, canonical hashing, and the existing local store.
        """
        normalized = validate_catalog(problems)
        payload_hash = self._hash({"operation": "import_catalog", "problems": normalized})
        connection = self._db()
        owns_snapshot = not connection.in_transaction
        if owns_snapshot:
            connection.execute("BEGIN")
        try:
            current = self.list_problems()
            lookup = {problem["id"]: problem for problem in current["problems"]}
            known_tags = {tag for problem in current["problems"] for tag in problem["tags"]}
            added = []
            unchanged = []
            conflicts = []
            for problem in normalized:
                existing = lookup.get(problem["id"])
                if existing is None:
                    added.append(problem)
                    continue
                existing = validate_catalog([existing])[0]
                fields = [field for field in CATALOG_METADATA_FIELDS if existing[field] != problem[field]]
                if fields:
                    conflicts.append({"problem_id": problem["id"], "fields": fields,
                                      "existing": existing, "incoming": problem})
                else:
                    unchanged.append(problem)
            blockers = []
            if conflicts:
                blockers.append({"code": "catalog_conflict",
                                 "message": "Existing problem metadata cannot be overwritten.",
                                 "details": {"problem_ids": [conflict["problem_id"] for conflict in conflicts]}})
            result = {
                "metadata_valid": True, "import_allowed": not conflicts,
                "catalog_version": current["catalog_version"], "payload_hash": payload_hash,
                "normalized_problems": normalized, "new_problems": added,
                "unchanged_problems": unchanged, "conflicts": conflicts, "blockers": blockers,
                "unknown_tags": sorted({tag for problem in normalized for tag in problem["tags"]} - known_tags),
                "verification": {"metadata_format_checked": True, "official_url_format_checked": True,
                                 "remote_source_checked": False, "content_correctness_checked": False},
            }
            if owns_snapshot:
                connection.commit()
            return result
        except BaseException:
            if owns_snapshot:
                connection.rollback()
            raise

    def import_catalog(self, problems: list[dict], submission_id: str, expected_hash: str | None = None) -> dict:
        """Inputs: metadata records, an operation ID, and an optional preview hash.
        Outputs: a committed append-only import receipt.

        Logic: check the content guard, replay safely, and reject all conflicting batches.
        Dependencies: strict metadata validation and one SQLite transaction.
        """
        _text(submission_id, "Submission ID")
        normalized = validate_catalog(problems)
        payload_hash = self._hash({"operation": "import_catalog", "problems": normalized})
        if expected_hash is not None:
            if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
                raise CoachError("validation_error", "Expected catalog hash must be a lowercase SHA-256 digest.")
            if expected_hash != payload_hash:
                raise CoachError("content_hash_mismatch", "Catalog content changed after preview.",
                                 {"expected_hash": expected_hash, "actual_hash": payload_hash})
        with storage.transaction(self._db()):
            replay = self._replay(submission_id, payload_hash)
            if replay is not None:
                return replay
            current = self.list_problems()
            lookup = {problem["id"]: problem for problem in current["problems"]}
            added = []
            for problem in normalized:
                existing = lookup.get(problem["id"])
                if existing is not None and validate_catalog([existing])[0] != problem:
                    raise CoachError("catalog_conflict", "Existing problem metadata cannot be overwritten.", {"problem_id": problem["id"]})
                if existing is None:
                    added.append(problem)
            catalog_version = current["catalog_version"]
            if added:
                for problem in added:
                    self._db().execute("INSERT INTO problems VALUES (?, ?)", (problem["id"], storage.canonical_json(problem)))
                combined = sorted([*current["problems"], *added], key=_problem_id)
                catalog_version = "import-" + self._hash({"problems": combined})
                self._db().execute("UPDATE metadata SET value = ? WHERE key = 'catalog_version'", (catalog_version,))
                self._refresh_state()
            receipt = {"submission_id": submission_id, "operation": "import_catalog", "added_count": len(added), "catalog_version": catalog_version, "state_version": self._state()["state_version"], "status": "applied", "saved_at": _now(), "payload_hash": payload_hash}
            self._db().execute("INSERT INTO submissions VALUES (?, ?, ?, ?)", (submission_id, "import_catalog", payload_hash, storage.canonical_json(receipt)))
        return self.receipt(submission_id)


def _problem_id(problem: dict) -> str:
    """Inputs: problem metadata. Outputs: its stable sort key.

    Logic: return the canonical identifier for deterministic catalog hashing.
    Dependencies: validated problem metadata.
    """
    return problem["id"]
