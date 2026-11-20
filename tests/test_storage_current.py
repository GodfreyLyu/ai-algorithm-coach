"""Verify current-schema storage boundaries with isolated synthetic authorities."""

import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.errors import CoachError
from algorithm_coach.service import Coach
from algorithm_coach.store import storage


class CurrentStorageTests(unittest.TestCase):
    """Keep initialization and reads independent of prior storage formats."""

    def setUp(self) -> None:
        """Inputs: none. Outputs: a private current-schema fixture.

        Logic: initialize a synthetic authority without a prior database.
        Dependencies: tempfile, pathlib, and Coach.initialize.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "private" / "coach.sqlite3"
        coach = Coach(self.path)
        try:
            coach.initialize()
        finally:
            coach.close()

    def tearDown(self) -> None:
        """Inputs: fixture resources. Outputs: none.

        Logic: remove only the isolated synthetic authority.
        Dependencies: tempfile cleanup.
        """
        self.temp.cleanup()

    def test_fresh_authority_contains_only_current_tables(self) -> None:
        """Inputs: a freshly initialized authority. Outputs: the current schema.

        Logic: compare actual tables with the complete current definition.
        Dependencies: storage.connect, CURRENT_TABLES, and SQLite metadata.
        """
        connection = storage.connect(self.path)
        try:
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
            self.assertEqual(names, storage.CURRENT_TABLES)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertFalse(any(name.startswith("legacy_") for name in names))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM learning_checkpoints").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM history_evidence").fetchone()[0], 0)
        finally:
            connection.close()

    def test_compatible_authority_reopens_without_changing_saved_rows(self) -> None:
        """Inputs: a populated current database. Outputs: unchanged persisted data.

        Logic: open and validate twice without changing headers or learning facts.
        Dependencies: the current storage boundary and local file bytes.
        """
        before = self.path.read_bytes()
        for _ in range(2):
            connection = storage.connect(self.path)
            connection.close()
        self.assertEqual(self.path.read_bytes(), before)

    def test_other_versions_fail_without_rewriting_the_authority(self) -> None:
        """Inputs: matching application IDs with noncurrent version headers.
        Outputs: an actionable schema mismatch and unchanged files.

        Logic: reject each incompatible version before reading or modifying records.
        Dependencies: SQLite header pragmas, CoachError, and storage.connect.
        """
        for version in (0, 1, 2, 3, 5):
            with self.subTest(version=version):
                connection = sqlite3.connect(self.path)
                connection.execute(f"PRAGMA user_version = {version}")
                connection.close()
                before = self.path.read_bytes()
                with self.assertRaises(CoachError) as raised:
                    storage.connect(self.path)
                self.assertEqual(raised.exception.code, "schema_mismatch")
                self.assertEqual(raised.exception.details, {"expected_version": 4, "actual_version": version})
                self.assertEqual(self.path.read_bytes(), before)
                with self.assertRaises(CoachError) as initialized:
                    storage.create(self.path)
                self.assertEqual(initialized.exception.code, "schema_mismatch")
                self.assertEqual(self.path.read_bytes(), before)

    def test_missing_required_table_fails_as_an_incomplete_schema(self) -> None:
        """Inputs: a current header with a missing native evidence table.
        Outputs: an incomplete-schema error naming the missing table.

        Logic: reject unsupported structure at the connection boundary.
        Dependencies: SQLite DDL and storage.check_schema.
        """
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TABLE history_evidence")
        connection.close()
        with self.assertRaises(CoachError) as raised:
            storage.connect(self.path)
        self.assertEqual(raised.exception.code, "unsupported_database")
        self.assertEqual(raised.exception.details, {"missing_tables": ["history_evidence"]})

    def test_checkpoints_and_unbound_evidence_are_immutable(self) -> None:
        """Inputs: native checkpoint and historical evidence records.
        Outputs: retained facts after rejected updates and deletes.

        Logic: enforce append-only evidence without requiring a bound attempt.
        Dependencies: current table triggers and a synthetic catalog problem.
        """
        connection = storage.connect(self.path)
        try:
            connection.execute("INSERT INTO learning_checkpoints VALUES (?, ?, ?, ?)",
                               ("leetcode:1", "Java", '{"state":{}}', "2026-01-01T00:00:00+00:00"))
            connection.execute("INSERT INTO history_evidence VALUES (?, ?, NULL, NULL, ?, ?)",
                               ("synthetic-history", "leetcode:1", "practice_note", '{"note":"Unknown round"}'))
            for table in ("learning_checkpoints", "history_evidence"):
                with self.subTest(table=table):
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute(f"UPDATE {table} SET body = '{{}}'")
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute(f"DELETE FROM {table}")
                    self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1)
        finally:
            connection.close()

    def test_failed_schema_creation_leaves_an_empty_retryable_file(self) -> None:
        """Inputs: an intentionally incomplete schema script.
        Outputs: rolled-back DDL and successful current initialization afterward.

        Logic: fail inside the caller's schema transaction and retry the same path.
        Dependencies: storage.create, transactional DDL, and unittest.mock.
        """
        from unittest.mock import patch

        target = Path(self.temp.name) / "retry" / "coach.sqlite3"
        with patch.object(storage, "SCHEMA", storage.SCHEMA + "\nINSERT INTO missing_table VALUES (1);\n"):
            with self.assertRaises(CoachError):
                storage.create(target)
        connection = sqlite3.connect(target)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sqlite_schema").fetchone()[0], 0)
        finally:
            connection.close()
        coach = Coach(target)
        try:
            self.assertTrue(coach.initialize()["initialized"])
        finally:
            coach.close()

    def test_missing_and_foreign_files_are_not_initialized_on_read(self) -> None:
        """Inputs: an absent path and an unrelated private SQLite file.
        Outputs: explicit errors without creating or replacing either source.

        Logic: distinguish missing storage from an unsupported application.
        Dependencies: local paths, SQLite, and storage.connect.
        """
        absent = Path(self.temp.name) / "absent" / "coach.sqlite3"
        with self.assertRaises(CoachError) as missing:
            storage.connect(absent)
        self.assertEqual(missing.exception.code, "not_initialized")
        self.assertFalse(absent.parent.exists())
        foreign = Path(self.temp.name) / "foreign.sqlite3"
        connection = sqlite3.connect(foreign)
        connection.execute("CREATE TABLE synthetic (value TEXT)")
        connection.close()
        os.chmod(foreign, 0o600)
        before = foreign.read_bytes()
        with self.assertRaises(CoachError) as rejected:
            storage.connect(foreign)
        self.assertEqual(rejected.exception.code, "unsupported_database")
        self.assertEqual(foreign.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
