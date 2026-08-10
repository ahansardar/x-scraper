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

            self.assertEqual(first, ("001",))
            self.assertEqual(second, ())
            self.assertEqual(runner.applied_versions(), ("001",))

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


if __name__ == "__main__":
    unittest.main()
