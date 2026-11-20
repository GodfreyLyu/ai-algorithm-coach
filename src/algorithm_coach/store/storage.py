"""Manage local SQLite connections, schema checks, and atomic transactions."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterator

from ..errors import CoachError
from .schema import CURRENT_TABLES, SCHEMA


APPLICATION_ID = 0x41414331
SCHEMA_VERSION = 4


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


def connect(path: Path) -> sqlite3.Connection:
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
        check_schema(connection)
        return connection
    except (sqlite3.Error, CoachError) as exc:
        if "connection" in locals():
            connection.close()
        if isinstance(exc, CoachError):
            raise
        raise CoachError("storage_error", "The database could not be opened safely.") from exc


def check_schema(connection: sqlite3.Connection) -> None:
    """Inputs: an open connection. Outputs: none, or a domain error.

    Logic: require the current application, schema, and initialized authority rows.
    Dependencies: SQLite header pragmas and current schema metadata.
    """
    application = connection.execute("PRAGMA application_id").fetchone()[0]
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if application != APPLICATION_ID:
        raise CoachError("unsupported_database", "This file is not a coach database.")
    if version != SCHEMA_VERSION:
        raise CoachError("schema_mismatch", "Use a database prepared for the current schema.",
                         {"expected_version": SCHEMA_VERSION, "actual_version": version})
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
    missing = CURRENT_TABLES - tables
    if missing:
        raise CoachError("unsupported_database", "The coach schema is incomplete.", {"missing_tables": sorted(missing)})
    try:
        config = connection.execute("SELECT revision FROM config WHERE singleton = 1").fetchone()
        state = connection.execute("SELECT version FROM learning_state WHERE singleton = 1").fetchone()
        baseline = connection.execute("SELECT revision FROM policies WHERE revision = 0").fetchone()
    except sqlite3.Error as exc:
        raise CoachError("unsupported_database", "The coach schema is incomplete.") from exc
    if config is None or state is None or baseline is None:
        raise CoachError("unsupported_database", "The coach initialization is incomplete.")


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
        if application == APPLICATION_ID:
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
