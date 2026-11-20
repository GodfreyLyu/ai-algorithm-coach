"""Test safe first-run recovery and preservation of unrelated local databases."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from algorithm_coach.errors import CoachError
from algorithm_coach.service import Coach


class InitializationTests(unittest.TestCase):
    """Exercise first-run failures without using any real learning records."""

    def test_interrupted_schema_creation_can_be_retried(self) -> None:
        """Recover from process death before initialization commits.

        Inputs: A new database and an initializer killed after schema creation.
        Outputs: A successful explicit retry with a complete configuration.
        Logic: Exit without cleanup, then let SQLite recover its transaction journal.
        Dependencies: A child Python process, SQLite rollback, and Coach.initialize.
        """
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "private" / "coach.sqlite3"
            child = subprocess.run(
                [sys.executable, "-S", "-c",
                 "import os, sys; from pathlib import Path; "
                 "sys.path.insert(0, sys.argv[1]); "
                 "from algorithm_coach.store import storage; "
                 "connection = storage.create(Path(sys.argv[2])); os._exit(17)",
                 str(ROOT / "src"), str(db)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(child.returncode, 17, child.stdout + child.stderr)
            coach = Coach(db)
            try:
                result = coach.initialize({"timezone": "UTC"})
                self.assertTrue(result["initialized"])
                self.assertEqual(coach.get_config()["config"]["timezone"], "UTC")
                self.assertEqual(coach.integrity_check()["status"], "ok")
            finally:
                coach.close()

    def test_initialization_does_not_replace_foreign_database(self) -> None:
        """Refuse an unrelated SQLite file without deleting its contents.

        Inputs: An existing database with a synthetic unrelated record.
        Outputs: An initialization error and the original record.
        Logic: Inspect schema ownership before creating any coach tables.
        Dependencies: SQLite, private file permissions, and Coach.
        """
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "coach.sqlite3"
            connection = sqlite3.connect(db)
            connection.execute("CREATE TABLE unrelated (value TEXT)")
            connection.execute("INSERT INTO unrelated VALUES ('synthetic-preserved')")
            connection.commit()
            connection.close()
            os.chmod(db, 0o600)
            coach = Coach(db)
            try:
                with self.assertRaises(CoachError):
                    coach.initialize()
            finally:
                coach.close()
            connection = sqlite3.connect(db)
            try:
                self.assertEqual(connection.execute("SELECT value FROM unrelated").fetchone()[0],
                                 "synthetic-preserved")
                self.assertIsNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'feedback'"
                ).fetchone())
            finally:
                connection.close()

    def test_invalid_first_configuration_creates_no_state(self) -> None:
        """Validate setup before reserving a private directory.

        Inputs: A missing path and an invalid timezone.
        Outputs: A domain error and no created directory.
        Logic: Check configuration before opening SQLite.
        Dependencies: Coach validation and pathlib.
        """
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "private" / "coach.sqlite3"
            coach = Coach(db)
            try:
                with self.assertRaises(CoachError):
                    coach.initialize({"timezone": "Invalid/Zone"})
                self.assertFalse(db.parent.exists())
            finally:
                coach.close()


if __name__ == "__main__":
    unittest.main()
