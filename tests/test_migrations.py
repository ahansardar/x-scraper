import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.migrations import MigrationRunner


EXPECTED_MIGRATIONS = ("001", "002", "003", "004", "005", "006", "007")


class MigrationRunnerTests(unittest.TestCase):
    def test_applies_baseline_migration_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            runner = MigrationRunner(
                db_path,
                ROOT / "src" / "xingestion" / "migrations" / "sql",
            )

            first = runner.apply()
            second = runner.apply()
            status = runner.status()

            self.assertEqual(first, EXPECTED_MIGRATIONS)
            self.assertEqual(second, ())
            self.assertEqual(runner.applied_versions(), EXPECTED_MIGRATIONS)
            self.assertTrue(status.current)
            self.assertEqual(status.pending_versions, ())

            with closing(sqlite3.connect(db_path)) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                session_columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(session_artifacts)"
                    ).fetchall()
                }
                protocol_attempt_columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(protocol_attempts)"
                    ).fetchall()
                }
            self.assertIn("capability_tasks", tables)
            self.assertIn("canonical_tweets", tables)
            self.assertIn("session_artifacts", tables)
            self.assertIn("protocol_release_health", tables)
            self.assertIn("approved_protocol_release", tables)
            self.assertIn("protocol_attempts", tables)
            self.assertIn("reprocess_jobs", tables)
            self.assertIn("attempt_count", session_columns)
            self.assertIn("last_error_class", session_columns)
            self.assertIn("network_context", protocol_attempt_columns)

    def test_status_reports_pending_migrations_before_apply(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            runner = MigrationRunner(
                db_path,
                ROOT / "src" / "xingestion" / "migrations" / "sql",
            )

            status = runner.status()

            self.assertFalse(status.current)
            self.assertEqual(status.available_versions, EXPECTED_MIGRATIONS)
            self.assertEqual(status.applied_versions, ())
            self.assertEqual(status.pending_versions, EXPECTED_MIGRATIONS)
            with self.assertRaisesRegex(RuntimeError, "Pending database migrations"):
                runner.require_current()


if __name__ == "__main__":
    unittest.main()
