"""Manage local SQLite connections, schema checks, and atomic transactions."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterator

from .errors import CoachError


APPLICATION_ID = 0x41414331
SCHEMA_VERSION = 2
SCHEMA_V1 = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE config (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    revision INTEGER NOT NULL, body TEXT NOT NULL
);
CREATE TABLE problems (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE attempts (
    id TEXT PRIMARY KEY, problem_id TEXT NOT NULL REFERENCES problems(id),
    language TEXT NOT NULL, kind TEXT NOT NULL,
    planned_date TEXT NOT NULL, source_attempt_id TEXT REFERENCES attempts(id),
    review_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE plans (
    id TEXT PRIMARY KEY, training_date TEXT NOT NULL UNIQUE,
    timezone TEXT NOT NULL, config_revision INTEGER NOT NULL,
    config_snapshot TEXT NOT NULL, state_version INTEGER NOT NULL,
    catalog_version TEXT NOT NULL, rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE plan_items (
    plan_id TEXT NOT NULL REFERENCES plans(id), position INTEGER NOT NULL,
    attempt_id TEXT NOT NULL REFERENCES attempts(id), reason TEXT NOT NULL,
    PRIMARY KEY(plan_id, position), UNIQUE(plan_id, attempt_id)
);
CREATE TABLE feedback (
    attempt_id TEXT NOT NULL REFERENCES attempts(id), revision INTEGER NOT NULL,
    submission_id TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
    changes TEXT NOT NULL, snapshot TEXT NOT NULL,
    practice_date TEXT NOT NULL, occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL, PRIMARY KEY(attempt_id, revision)
);
CREATE TABLE submissions (
    id TEXT PRIMARY KEY, operation TEXT NOT NULL,
    payload_hash TEXT NOT NULL, receipt TEXT NOT NULL
);
CREATE TABLE learning_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    version INTEGER NOT NULL, body TEXT NOT NULL
);
CREATE TABLE reviews (
    id TEXT PRIMARY KEY,
    source_attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id),
    problem_id TEXT NOT NULL REFERENCES problems(id), language TEXT NOT NULL,
    due_date TEXT NOT NULL, status TEXT NOT NULL,
    attempt_id TEXT UNIQUE REFERENCES attempts(id)
);
CREATE INDEX feedback_latest ON feedback(attempt_id, revision DESC);
CREATE INDEX attempts_problem ON attempts(problem_id, language);
CREATE TRIGGER feedback_no_update BEFORE UPDATE ON feedback
BEGIN SELECT RAISE(ABORT, 'Feedback history is immutable'); END;
CREATE TRIGGER feedback_no_delete BEFORE DELETE ON feedback
BEGIN SELECT RAISE(ABORT, 'Feedback history is immutable'); END;
CREATE TRIGGER submissions_no_update BEFORE UPDATE ON submissions
BEGIN SELECT RAISE(ABORT, 'Submission receipts are immutable'); END;
CREATE TRIGGER submissions_no_delete BEFORE DELETE ON submissions
BEGIN SELECT RAISE(ABORT, 'Submission receipts are immutable'); END;
"""
POLICY_SCHEMA = """
CREATE TABLE policy_proposals (
    id TEXT PRIMARY KEY, body TEXT NOT NULL, content_hash TEXT NOT NULL,
    base_revision INTEGER NOT NULL, config_revision INTEGER NOT NULL,
    catalog_version TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE policies (
    revision INTEGER PRIMARY KEY,
    proposal_id TEXT UNIQUE REFERENCES policy_proposals(id),
    body TEXT NOT NULL, content_hash TEXT NOT NULL, activated_at TEXT NOT NULL
);
ALTER TABLE plans ADD COLUMN policy_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE plans ADD COLUMN policy_snapshot TEXT NOT NULL DEFAULT '{}';
ALTER TABLE plans ADD COLUMN diagnostics TEXT NOT NULL DEFAULT '{}';
CREATE TRIGGER proposals_no_update BEFORE UPDATE ON policy_proposals
BEGIN SELECT RAISE(ABORT, 'Policy proposals are immutable'); END;
CREATE TRIGGER proposals_no_delete BEFORE DELETE ON policy_proposals
BEGIN SELECT RAISE(ABORT, 'Policy proposals are immutable'); END;
CREATE TRIGGER policies_no_update BEFORE UPDATE ON policies
BEGIN SELECT RAISE(ABORT, 'Policy activations are immutable'); END;
CREATE TRIGGER policies_no_delete BEFORE DELETE ON policies
BEGIN SELECT RAISE(ABORT, 'Policy activations are immutable'); END;
"""
SCHEMA = SCHEMA_V1 + POLICY_SCHEMA


def canonical_json(value: object) -> str:
    """Inputs: a JSON value. Outputs: stable JSON text.

    Logic: sort object keys and reject non-finite numbers.
    Dependencies: Python's json module.
    """
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CoachError("validation_error", "Input must contain valid JSON values.") from exc


def decode_object(value: str, label: str) -> dict:
    """Inputs: stored JSON text and its label. Outputs: a decoded object.

    Logic: reject malformed JSON, non-finite values, and unexpected root types.
    Dependencies: json and CoachError; stored data is never treated as user input.
    """
    try:
        result = json.loads(value)
        if not isinstance(result, dict):
            raise ValueError("Expected a JSON object")
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise CoachError("integrity_error", f"Stored {label} is not a valid JSON object.") from exc
    return result


def connect(path: Path, allow_legacy: bool = False) -> sqlite3.Connection:
    """Inputs: an existing database path. Outputs: a configured connection.

    Logic: open without implicit transactions and enable integrity settings.
    Dependencies: sqlite3 and a local, existing regular file.
    """
    if path.is_symlink() or not path.is_file():
        raise CoachError("not_initialized", "Initialize a regular local database first.")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise CoachError("insecure_permissions", "The database must be private to its owner (mode 600).")
    try:
        connection = sqlite3.connect(str(path), isolation_level=None, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = FULL")
        check_schema(connection, allow_legacy)
        return connection
    except (sqlite3.Error, CoachError) as exc:
        if "connection" in locals():
            connection.close()
        if isinstance(exc, CoachError):
            raise
        raise CoachError("storage_error", "The database could not be opened safely.") from exc


def check_schema(connection: sqlite3.Connection, allow_legacy: bool = False) -> None:
    """Inputs: an open connection. Outputs: none, or a domain error.

    Logic: reject unknown applications and unsupported schema versions.
    Dependencies: SQLite header pragmas and the expected metadata tables.
    """
    application = connection.execute("PRAGMA application_id").fetchone()[0]
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if application == APPLICATION_ID and version == 1 and not allow_legacy:
        raise CoachError("migration_required", "Back up and run the explicit migrate command for schema version 2.")
    if application != APPLICATION_ID or version not in ((1, SCHEMA_VERSION) if allow_legacy else (SCHEMA_VERSION,)):
        raise CoachError("unsupported_database", "This file is not a supported coach database.")
    try:
        config = connection.execute("SELECT revision FROM config WHERE singleton = 1").fetchone()
        state = connection.execute("SELECT version FROM learning_state WHERE singleton = 1").fetchone()
        if config is None or state is None:
            raise CoachError("unsupported_database", "The coach initialization is incomplete.")
        if version == SCHEMA_VERSION:
            connection.execute("SELECT revision FROM policies WHERE revision = 0").fetchone()
            connection.execute("SELECT id FROM policy_proposals LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        raise CoachError("unsupported_database", "The coach schema is incomplete.") from exc


def apply_schema(connection: sqlite3.Connection, script: str) -> None:
    """Inputs: a connection and SQL script. Outputs: none.

    Logic: execute complete statements without committing the caller's transaction.
    Dependencies: sqlite3.complete_statement; trigger bodies remain intact.
    """
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise CoachError("storage_error", "The schema script contains an incomplete statement.")


def create(path: Path) -> sqlite3.Connection:
    """Inputs: a new or crash-empty path. Outputs: an open schema transaction.

    Logic: lock first, reject foreign data, and leave schema creation uncommitted.
    Dependencies: file permissions, SQLite journaling, and a caller that seeds data.
    """
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise CoachError("unsupported_database", "Initialization requires a regular local file.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if path.is_symlink() or not path.is_file():
            raise CoachError("unsupported_database", "Initialization requires a regular local file.")
    else:
        os.close(descriptor)
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise CoachError("insecure_permissions", "The database must be private to its owner (mode 600).")
    connection = sqlite3.connect(str(path), isolation_level=None, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("BEGIN IMMEDIATE")
        application = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if application == APPLICATION_ID and version == SCHEMA_VERSION:
            check_schema(connection)
            raise CoachError("already_initialized", "Another initializer completed; read the saved configuration.")
        existing = connection.execute("SELECT name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if application != 0 or version != 0 or existing:
            raise CoachError("unsupported_database", "Initialization will not modify a foreign or incomplete schema.")
        apply_schema(connection, SCHEMA)
        connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return connection
    except BaseException as exc:
        if connection.in_transaction:
            connection.rollback()
        connection.close()
        if isinstance(exc, sqlite3.Error):
            raise CoachError("storage_error", "Initialization failed; retry the same local path safely.") from exc
        raise


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Inputs: a connection. Outputs: an atomic write context.

    Logic: acquire the writer lock, commit success, and roll back any failure.
    Dependencies: SQLite transactions; no network or model calls occur here.
    """
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield
        connection.execute("COMMIT")
    except BaseException as exc:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        if isinstance(exc, sqlite3.Error):
            raise CoachError("storage_error", "The database operation failed; retry safely.") from exc
        raise
