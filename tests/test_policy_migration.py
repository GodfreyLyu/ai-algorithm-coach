"""Test explicit policy schema migration without losing legacy learning records."""

import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.catalog import CATALOG_VERSION, PROBLEMS
from algorithm_coach.errors import CoachError
from algorithm_coach.rules import default_config, derive_learning_state, merge_feedback
from algorithm_coach.service import Coach
from algorithm_coach import storage


def create_legacy_database(path: Path) -> dict:
    """Create a populated schema-one fixture from its preserved schema contract.

    Inputs: A new private database path.
    Outputs: The saved legacy receipt and feedback snapshot.
    Logic: Seed one frozen plan, unfinished practice, revision, and permanent receipt.
    Dependencies: SQLite, SCHEMA_V1, metadata, and pure feedback rules.
    """
    path.parent.mkdir(mode=0o700)
    connection = sqlite3.connect(path, isolation_level=None)
    os.chmod(path, 0o600)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + storage.SCHEMA_V1)
        config = default_config()
        snapshot = merge_feedback(None, {"result": "D", "elapsed_minutes": 20, "boundary_tests": False})
        receipt = {"submission_id": "legacy-operation", "operation": "submit_feedback",
                   "attempt_id": "legacy-attempt", "revision": 1, "payload_hash": "a" * 64,
                   "state_version": 1, "status": "applied", "saved_at": "2026-01-01T12:00:00+00:00"}
        connection.execute("INSERT INTO metadata VALUES ('workspace_id', 'synthetic-legacy-workspace')")
        connection.execute("INSERT INTO metadata VALUES ('catalog_version', ?)", (CATALOG_VERSION,))
        connection.execute("INSERT INTO config VALUES (1, 1, ?)", (storage.canonical_json(config),))
        for problem in PROBLEMS:
            connection.execute("INSERT INTO problems VALUES (?, ?)",
                               (problem["id"], storage.canonical_json(problem)))
        connection.execute("INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           ("legacy-attempt", "leetcode:1", "Java", "practice", "2026-01-01",
                            None, None, "2026-01-01T10:00:00+00:00"))
        connection.execute("INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           ("legacy-attempt", 1, "legacy-operation", "progress",
                            storage.canonical_json({"result": "D", "elapsed_minutes": 20, "boundary_tests": False}),
                            storage.canonical_json(snapshot), "2026-01-01",
                            "2026-01-01T12:00:00+00:00", "2026-01-01T12:00:00+00:00"))
        connection.execute("INSERT INTO submissions VALUES (?, ?, ?, ?)",
                           ("legacy-operation", "submit_feedback", "a" * 64, storage.canonical_json(receipt)))
        attempts = [{"id": "legacy-attempt", "problem_id": "leetcode:1", "language": "Java",
                     "planned_date": "2026-01-01", "practice_date": "2026-01-01", "feedback": snapshot}]
        state = derive_learning_state(attempts, config)
        connection.execute("INSERT INTO learning_state VALUES (1, 1, ?)", (storage.canonical_json(state),))
        connection.execute("INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           ("legacy-plan", "2026-01-01", "UTC", 1, storage.canonical_json(config),
                            0, CATALOG_VERSION, "1", "2026-01-01T10:00:00+00:00"))
        connection.execute("INSERT INTO plan_items VALUES ('legacy-plan', 1, 'legacy-attempt', 'foundation')")
        connection.execute(f"PRAGMA application_id = {storage.APPLICATION_ID}")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
        return {"receipt": receipt, "snapshot": snapshot}
    finally:
        connection.close()


class MigrationTests(unittest.TestCase):
    """Check safe explicit upgrades and rollback with populated legacy databases."""

    def setUp(self) -> None:
        """Prepare a private legacy authority.

        Inputs: None.
        Outputs: A populated schema-one database and a lazy current Coach.
        Logic: Avoid using an ignored distribution bundle as a test dependency.
        Dependencies: tempfile and create_legacy_database.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "private" / "coach.sqlite3"
        self.legacy = create_legacy_database(self.path)
        self.coach = Coach(self.path)

    def tearDown(self) -> None:
        """Release the database and automatic test backups.

        Inputs: The fixture.
        Outputs: None.
        Logic: Close SQLite before removing the temporary parent.
        Dependencies: Coach and tempfile.
        """
        self.coach.close()
        self.temp.cleanup()

    def test_reads_require_explicit_migration(self) -> None:
        """Keep ordinary reads from silently changing an old schema.

        Inputs: A populated legacy database.
        Outputs: A migration_required error and unchanged schema version.
        Logic: Inspect the raw schema after a rejected current-version read.
        Dependencies: Coach and SQLite schema version metadata.
        """
        with self.assertRaises(CoachError) as raised:
            self.coach.learning_state()
        self.assertEqual(raised.exception.code, "migration_required")
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'policies'").fetchone())
        finally:
            connection.close()

    def test_upgrade_preserves_history_receipts_and_plan_membership(self) -> None:
        """Upgrade storage while preserving all prior learning facts.

        Inputs: A legacy database with one immutable operation.
        Outputs: A valid schema-two authority and a verified schema-one backup.
        Logic: Compare existing public records after migration and repeated migration.
        Dependencies: Coach.migrate, SQLite backup, and schema checks.
        """
        result = self.coach.migrate()
        self.assertTrue(result["migrated"])
        self.assertEqual(result["schema_version"], 2)
        backup = Path(result["backup_path"])
        self.assertTrue(backup.is_file())
        connection = sqlite3.connect(backup)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT snapshot FROM feedback").fetchone()[0],
                             storage.canonical_json(self.legacy["snapshot"]))
        finally:
            connection.close()
        self.assertEqual(self.coach.receipt("legacy-operation"), self.legacy["receipt"])
        history = self.coach.history("legacy-attempt")
        self.assertEqual(history["attempt"]["feedback"], self.legacy["snapshot"])
        self.assertEqual(len(history["revisions"]), 1)
        plan = self.coach.ensure_plan("2026-01-01")
        self.assertFalse(plan["created"])
        self.assertEqual(plan["items"][0]["attempt_id"], "legacy-attempt")
        self.assertEqual(plan["policy_revision"], 0)
        self.assertEqual(self.coach.integrity_check()["status"], "ok")
        self.assertFalse(self.coach.migrate()["migrated"])

    def test_failed_upgrade_rolls_back_all_ddl_and_can_be_retried(self) -> None:
        """Recover from failure after policy tables and columns were created.

        Inputs: A migration whose final SQL statement intentionally fails.
        Outputs: Unchanged legacy data, no policy tables, and a successful retry.
        Logic: Fail within the actual migration transaction rather than before it.
        Dependencies: SQLite transactional DDL and a patched migration script.
        """
        broken = storage.POLICY_SCHEMA + "\nINSERT INTO synthetic_missing_table VALUES (1);\n"
        with patch.object(storage, "POLICY_SCHEMA", broken):
            with self.assertRaises(CoachError):
                self.coach.migrate()
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'policies'").fetchone())
            columns = [row[1] for row in connection.execute("PRAGMA table_info(plans)")]
            self.assertNotIn("policy_revision", columns)
            self.assertEqual(connection.execute("SELECT snapshot FROM feedback").fetchone()[0],
                             storage.canonical_json(self.legacy["snapshot"]))
        finally:
            connection.close()
        self.assertTrue(self.coach.migrate()["migrated"])
        self.assertEqual(self.coach.receipt("legacy-operation"), self.legacy["receipt"])

    def test_backup_is_available_before_migration(self) -> None:
        """Let owners take an explicit consistent snapshot before upgrading.

        Inputs: A supported legacy authority and a new backup destination.
        Outputs: A verified schema-one backup without an upgrade.
        Logic: Use the backup operation's supported legacy read path.
        Dependencies: Coach.backup and SQLite.
        """
        destination = Path(self.temp.name) / "manual-backup.sqlite3"
        result = self.coach.backup(destination)
        self.assertEqual(result["schema_version"], 1)
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
