import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.migrations import MigrationRunner


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

            self.assertEqual(first, ("001",))
            self.assertEqual(second, ())
            self.assertEqual(runner.applied_versions(), ("001",))
            self.assertTrue(status.current)
            self.assertEqual(status.pending_versions, ())

            with closing(sqlite3.connect(db_path)) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
            self.assertIn("capability_tasks", tables)
            self.assertIn("canonical_tweets", tables)
            self.assertIn("session_artifacts", tables)
            self.assertIn("protocol_release_health", tables)

    def test_status_reports_pending_migrations_before_apply(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            runner = MigrationRunner(
                db_path,
                ROOT / "src" / "xingestion" / "migrations" / "sql",
            )

            status = runner.status()

            self.assertFalse(status.current)
            self.assertEqual(status.available_versions, ("001",))
            self.assertEqual(status.applied_versions, ())
            self.assertEqual(status.pending_versions, ("001",))
            with self.assertRaisesRegex(RuntimeError, "Pending database migrations"):
                runner.require_current()


if __name__ == "__main__":
    unittest.main()
