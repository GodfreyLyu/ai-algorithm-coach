"""Persist code evidence and scoped host-model reviews without calling a model API."""

from datetime import datetime, timezone
import hashlib
from uuid import uuid4

from .errors import CoachError
from . import storage


def _now() -> str:
    """Inputs: none. Outputs: a UTC timestamp.

    Logic: retain the actual receipt time independently of practice time.
    Dependencies: datetime and the host clock.
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _text(value: object, label: str, limit: int = 4000) -> str:
    """Inputs: text, a label, and a length limit. Outputs: validated text.

    Logic: reject missing text without rewriting original source code.
    Dependencies: CoachError.
    """
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise CoachError("validation_error", f"{label} must be non-empty text of at most {limit} characters.")
    return value


class ComplexityMixin:
    """Add durable evidence and review use cases to the shared service."""

    def _save_operation(self, submission_id: str, operation: str, payload_hash: str, fields: dict) -> dict:
        """Inputs: operation identity and receipt fields. Outputs: a receipt.

        Logic: persist the acknowledgment inside the caller's transaction.
        Dependencies: immutable submissions and canonical JSON.
        """
        receipt = {"submission_id": submission_id, "operation": operation,
                   "payload_hash": payload_hash, "status": "applied", "saved_at": _now(), **fields}
        self._db().execute("INSERT INTO submissions VALUES (?, ?, ?, ?)",
                           (submission_id, operation, payload_hash, storage.canonical_json(receipt)))
        return receipt

    def record_solution(self, attempt_id: str, submission_id: str, expected_revision: int, document: dict) -> dict:
        """Inputs: an attempt, stable ID, feedback version, and code document.
        Outputs: the committed evidence identity and content hash.

        Logic: bind immutable code to an exact feedback revision before review.
        Dependencies: the current attempt, SQLite transactions, and SHA-256.
        """
        _text(submission_id, "Submission ID", 200)
        self._revision(expected_revision)
        if not isinstance(document, dict) or set(document) - {"code", "language", "input_definition"}:
            raise CoachError("validation_error", "Solution documents accept code, language, and input_definition.")
        code = _text(document.get("code"), "Code", 200000)
        language = _text(document.get("language"), "Language", 40)
        if document.get("input_definition") is not None:
            _text(document["input_definition"], "Input definition")
        payload_hash = self._hash({"operation": "record_solution", "attempt_id": attempt_id,
                                   "expected_revision": expected_revision, "document": document})
        with storage.transaction(self._db()):
            replay = self._replay(submission_id, payload_hash)
            if replay is not None:
                return replay
            attempt = self._attempt(attempt_id)
            if attempt["revision"] != expected_revision:
                raise CoachError("revision_conflict", "Feedback changed; reload the attempt first.")
            if language != attempt["language"]:
                raise CoachError("validation_error", "Code language must match the practice attempt.")
            evidence_id = str(uuid4())
            code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
            body = {**document, "language": language}
            self._db().execute("INSERT INTO solution_evidence VALUES (?, ?, ?, ?, ?, ?)",
                               (evidence_id, attempt_id, expected_revision, code_hash, storage.canonical_json(body), _now()))
            self._refresh_state()
            receipt = self._save_operation(submission_id, "record_solution", payload_hash,
                                           {"attempt_id": attempt_id, "feedback_revision": expected_revision,
                                            "evidence_id": evidence_id, "code_hash": code_hash})
        return receipt

    def submit_complexity_review(self, submission_id: str, document: dict) -> dict:
        """Inputs: a stable ID and host-authored review. Outputs: its receipt.

        Logic: reject stale evidence and store a scoped analysis separately from reports.
        Dependencies: solution evidence, the current feedback version, and transactions.
        """
        _text(submission_id, "Submission ID", 200)
        fields = {"evidence_id", "status", "input_definition", "time_complexity", "space_complexity",
                  "reasoning", "sources", "reviewer", "learning_evidence"}
        if not isinstance(document, dict) or set(document) - fields:
            raise CoachError("validation_error", "The review contains unsupported fields.")
        for field in ("evidence_id", "input_definition", "reasoning", "reviewer"):
            _text(document.get(field), field, 16000 if field == "reasoning" else 4000)
        if document.get("status") not in {"supported", "issues", "insufficient_information"}:
            raise CoachError("validation_error", "Review status must be supported, issues, or insufficient_information.")
        for field in ("time_complexity", "space_complexity"):
            if document.get("status") != "insufficient_information" or document.get(field) is not None:
                _text(document.get(field), field)
        if not isinstance(document.get("sources", []), list) or not all(isinstance(x, str) for x in document.get("sources", [])):
            raise CoachError("validation_error", "Review sources must be an array of source descriptions or URLs.")
        learning = document.get("learning_evidence", {})
        if not isinstance(learning, dict) or set(learning) - {"invariant", "correctness", "complexity", "boundary", "on_time", "key_error", "severe_dependence"}:
            raise CoachError("validation_error", "Learning evidence has unsupported fields.")
        if any(value is not None and type(value) is not bool for value in learning.values()):
            raise CoachError("validation_error", "Learning evidence values must be boolean or unknown.")
        payload_hash = self._hash({"operation": "complexity_review", "document": document})
        with storage.transaction(self._db()):
            replay = self._replay(submission_id, payload_hash)
            if replay is not None:
                return replay
            evidence = self._db().execute("SELECT * FROM solution_evidence WHERE id = ?", (document["evidence_id"],)).fetchone()
            if evidence is None:
                raise CoachError("not_found", "Solution evidence does not exist.")
            attempt = self._attempt(evidence["attempt_id"])
            latest = self._db().execute("SELECT id FROM solution_evidence WHERE attempt_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (attempt["id"],)).fetchone()
            if attempt["revision"] != evidence["feedback_revision"] or latest[0] != evidence["id"]:
                raise CoachError("revision_conflict", "This solution or feedback version is stale.")
            review_id = str(uuid4())
            self._db().execute("INSERT INTO complexity_reviews VALUES (?, ?, ?, ?)",
                               (review_id, evidence["id"], storage.canonical_json(document), _now()))
            self._refresh_state()
            receipt = self._save_operation(submission_id, "complexity_review", payload_hash,
                                           {"review_id": review_id, "evidence_id": evidence["id"],
                                            "attempt_id": attempt["id"], "feedback_revision": attempt["revision"],
                                            "code_hash": evidence["code_hash"]})
        return receipt

    def _complexity_item(self, attempt: dict) -> dict:
        """Inputs: a current attempt snapshot. Outputs: its review status.

        Logic: select the latest code and review while exposing stale version bindings.
        Dependencies: immutable evidence and review tables. This does not call _attempts.
        """
        row = self._db().execute("SELECT * FROM solution_evidence WHERE attempt_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (attempt["id"],)).fetchone()
        evidence = None
        review = None
        status = "awaiting_code"
        if row is not None:
            evidence = {**dict(row), "body": storage.decode_object(row["body"], "solution evidence")}
            found = self._db().execute("SELECT * FROM complexity_reviews WHERE evidence_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (row["id"],)).fetchone()
            if found is not None:
                review = {**dict(found), "body": storage.decode_object(found["body"], "complexity review")}
            status = review["body"]["status"] if review else "pending"
            if row["feedback_revision"] != attempt["revision"]:
                status = "stale"
        return {"attempt_id": attempt["id"], "feedback_revision": attempt["revision"],
                "status": status, "evidence": evidence, "review": review}

    def complexity_status(self, attempt_id: str | None = None) -> dict:
        """Inputs: an optional attempt ID. Outputs: review work and saved conclusions.

        Logic: keep missing-code and pending work visible until a host session reviews it.
        Dependencies: current attempts and _complexity_item. No API or background model runs.
        """
        attempts = [self._attempt(attempt_id)] if attempt_id is not None else self._attempts()
        return {"items": [self._complexity_item(attempt) for attempt in attempts],
                "model_api": False, "execution": "host_session"}

    def save_training_context(self, submission_id: str, document: dict) -> dict:
        """Inputs: a stable ID and researched problem context. Outputs: a receipt.

        Logic: append framework, source, and score evidence without changing catalog facts.
        Dependencies: the training profile validator, current catalog, and transactions.
        """
        from .training_profile import validate_training_context

        _text(submission_id, "Submission ID", 200)
        if not isinstance(document, dict) or set(document) - {"problem_id", "attempt_id", "context"}:
            raise CoachError("validation_error", "Use problem_id, optional attempt_id, and context.")
        problem_id = _text(document.get("problem_id"), "Problem ID", 200)
        context = validate_training_context(document.get("context"))
        payload_hash = self._hash({"operation": "training_context", "document": document})
        with storage.transaction(self._db()):
            replay = self._replay(submission_id, payload_hash)
            if replay is not None:
                return replay
            if self._db().execute("SELECT id FROM problems WHERE id = ?", (problem_id,)).fetchone() is None:
                raise CoachError("not_found", "The problem is not in the catalog.")
            attempt_id = document.get("attempt_id")
            if attempt_id is not None:
                attempt = self._attempt(attempt_id)
                if attempt["problem_id"] != problem_id:
                    raise CoachError("validation_error", "The context attempt belongs to another problem.")
                context = {**attempt.get("training_context", {}), **context}
            else:
                previous = self._db().execute("SELECT body FROM training_contexts WHERE problem_id = ? AND attempt_id IS NULL ORDER BY id DESC LIMIT 1", (problem_id,)).fetchone()
                if previous is not None:
                    context = {**storage.decode_object(previous[0], "candidate context"), **context}
            row = self._db().execute("INSERT INTO training_contexts(problem_id, attempt_id, body, created_at) VALUES (?, ?, ?, ?)",
                                     (problem_id, attempt_id, storage.canonical_json(context), _now()))
            receipt = self._save_operation(submission_id, "training_context", payload_hash, {"context_id": row.lastrowid})
            self._refresh_state()
        return receipt
