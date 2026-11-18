"""Read current practice records, selection history, and learning checkpoints."""

from .errors import CoachError
from . import storage


class PracticeRecordsMixin:
    """Provide native record queries for the shared application service."""

    def _attempts(self) -> list[dict]:
        """Inputs: none. Outputs: effective attempts with native context and evidence.

        Logic: join one feedback revision per attempt and bind language-specific checkpoints.
        Dependencies: current schema tables and scoped complexity readers.
        """
        connection = self._db()
        rows = connection.execute(
            "SELECT a.*, f.revision, f.snapshot, f.practice_date, f.occurred_at, f.received_at "
            "FROM attempts a LEFT JOIN feedback f ON f.attempt_id = a.id AND f.revision = "
            "(SELECT MAX(x.revision) FROM feedback x WHERE x.attempt_id = a.id) "
            "ORDER BY a.created_at, a.id"
        ).fetchall()
        contexts = {}
        for row in connection.execute("SELECT attempt_id, body FROM training_contexts WHERE attempt_id IS NOT NULL ORDER BY id"):
            contexts[row["attempt_id"]] = storage.decode_object(row["body"], "practice context")
        checkpoints = {(row["problem_id"], row["language"]): storage.decode_object(row["body"], "learning checkpoint")
                       for row in connection.execute("SELECT problem_id, language, body FROM learning_checkpoints")}
        result = []
        for row in rows:
            attempt = dict(row)
            snapshot = attempt.pop("snapshot")
            attempt["feedback"] = storage.decode_object(snapshot, "feedback") if snapshot is not None else None
            attempt["revision"] = attempt["revision"] or 0
            attempt["created_on"] = attempt["planned_date"]
            attempt["practice_date"] = attempt["practice_date"] or attempt["planned_date"]
            attempt["training_context"] = contexts.get(attempt["id"], {})
            checkpoint = checkpoints.get((attempt["problem_id"], attempt["language"]))
            if checkpoint is not None:
                attempt["learning_checkpoint"] = checkpoint
            review = self._complexity_item(attempt)
            evidence_id = review["evidence"]["id"] if review["evidence"] else None
            review_id = review["review"]["id"] if review["review"] else None
            attempt["assessment_version"] = self._hash({"evidence_id": evidence_id, "review_id": review_id,
                                                         "status": review["status"]})
            if review["review"] is not None and review["status"] != "stale":
                attempt["assessment"] = review["review"]["body"].get("learning_evidence", {})
            result.append(attempt)
        return result

    def _attempt(self, attempt_id: str) -> dict:
        """Inputs: an attempt ID. Outputs: its current projection.

        Logic: resolve one identity from the shared native record reader.
        Dependencies: _attempts and CoachError for an unknown target.
        """
        for attempt in self._attempts():
            if attempt["id"] == attempt_id:
                return attempt
        raise CoachError("not_found", "The practice attempt does not exist.")

    def _selection_context(self, training_date: str) -> dict:
        """Inputs: a validated date. Outputs: candidate research and assignment history.

        Logic: use native selection evidence and frozen plans while keeping recent order.
        Dependencies: training contexts, history evidence, plans, and current attempts.
        """
        connection = self._db()
        candidates = {}
        for row in connection.execute("SELECT problem_id, body FROM training_contexts WHERE attempt_id IS NULL ORDER BY id"):
            candidates[row["problem_id"]] = storage.decode_object(row["body"], "candidate research")
        history = [storage.decode_object(row[0], "selection history") for row in connection.execute(
            "SELECT body FROM history_evidence WHERE kind = 'selection' ORDER BY occurred_at, id")]
        recent = connection.execute("SELECT id FROM plans WHERE training_date < ? ORDER BY training_date DESC LIMIT 1", (training_date,)).fetchone()
        recent_ids = [row[0] for row in connection.execute("SELECT attempt_id FROM plan_items WHERE plan_id = ? ORDER BY position", (recent[0],))] if recent else []
        attempts = {attempt["id"]: attempt for attempt in self._attempts()}
        for row in connection.execute("SELECT p.training_date, i.attempt_id FROM plan_items i JOIN plans p ON p.id = i.plan_id WHERE p.training_date < ? ORDER BY p.training_date, i.position", (training_date,)):
            attempt = attempts[row["attempt_id"]]
            history.append({"date": row["training_date"], "problem_id": attempt["problem_id"],
                            **attempt["training_context"]})
        return {"candidates": candidates, "history": history, "recent_plan": recent_ids}

    def _history_evidence(self, column: str, value: str) -> list[dict]:
        """Inputs: an internal identity column and value. Outputs: source evidence.

        Logic: decode records without treating notes as independent practice attempts.
        Dependencies: trusted callers choose one fixed schema column.
        """
        rows = self._db().execute(
            f"SELECT * FROM history_evidence WHERE {column} = ? ORDER BY occurred_at, id", (value,))
        return [{**dict(row), "body": storage.decode_object(row["body"], "history evidence")} for row in rows]

    def _feedback_history(self, attempt: dict) -> dict:
        """Inputs: a resolved attempt. Outputs: its immutable feedback history.

        Logic: retain each revision's source and occurrence timestamps.
        Dependencies: feedback and history evidence tables.
        """
        revisions = []
        for row in self._db().execute("SELECT * FROM feedback WHERE attempt_id = ? ORDER BY revision", (attempt["id"],)):
            item = dict(row)
            item["changes"] = storage.decode_object(item["changes"], "feedback changes")
            item["snapshot"] = storage.decode_object(item["snapshot"], "feedback snapshot")
            revisions.append(item)
        return {"attempt": attempt, "revisions": revisions,
                "evidence": self._history_evidence("attempt_id", attempt["id"])}

    def history(self, attempt_id: str) -> dict:
        """Inputs: an attempt ID. Outputs: current data and immutable evidence.

        Logic: resolve the requested identity once before reading its history.
        Dependencies: native attempt and feedback readers.
        """
        return self._feedback_history(self._attempt(attempt_id))

    def history_for_problem(self, problem_id: str) -> dict:
        """Inputs: a canonical problem ID. Outputs: its practice and source history.

        Logic: keep unbound notes queryable without allocating or completing practice.
        Dependencies: public catalog metadata, attempts, evidence, and checkpoints.
        """
        row = self._db().execute("SELECT body FROM problems WHERE id = ?", (problem_id,)).fetchone()
        if row is None:
            raise CoachError("not_found", "The problem is not in the local catalog.")
        attempts = [item for item in self._attempts() if item["problem_id"] == problem_id]
        checkpoints = [{"language": item["language"], "body": storage.decode_object(item["body"], "learning checkpoint")}
                       for item in self._db().execute("SELECT language, body FROM learning_checkpoints WHERE problem_id = ? ORDER BY language", (problem_id,))]
        return {"problem_id": problem_id, "problem": storage.decode_object(row[0], "problem metadata"),
                "attempts": [self._feedback_history(attempt) for attempt in attempts],
                "evidence": self._history_evidence("problem_id", problem_id), "checkpoints": checkpoints}
