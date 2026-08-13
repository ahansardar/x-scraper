import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from psycopg_pool import ConnectionPool

from postgres_fixture import probe_reachable, test_dsn

from xingestion.migrations import PostgresMigrationRunner
from xingestion.tasks import PostgresTaskLedger

EXPECTED_MIGRATIONS = ("001", "002")


class PostgresMigrationRunnerTests(unittest.TestCase):
    def setUp(self):
        try:
            probe_reachable(test_dsn())
            # max_size=1 makes connection reuse across consumers deterministic,
            # which matters for test_status_survives_a_pool_connection_previously_used_with_dict_row.
            self.pool = ConnectionPool(test_dsn(), min_size=1, max_size=1, open=True, timeout=3)
            self.pool.wait(timeout=5)
        except Exception as exc:  # pragma: no cover - environment dependent
            self.skipTest(f"Postgres unavailable: {exc}")

    def tearDown(self):
        self.pool.close()

    def test_applies_baseline_migration_once(self):
        runner = PostgresMigrationRunner(
            self.pool,
            ROOT / "src" / "xingestion" / "migrations" / "postgres_sql",
        )

        # Idempotent regardless of whether this shared dev database already
        # has "001" applied from a prior run: apply() must converge to
        # "current" and a second call must be a no-op either way.
        runner.apply()
        second = runner.apply()
        status = runner.status()

        self.assertEqual(second, ())
        self.assertEqual(runner.applied_versions(), EXPECTED_MIGRATIONS)
        self.assertTrue(status.current)
        self.assertEqual(status.pending_versions, ())

    def test_status_survives_a_pool_connection_previously_used_with_dict_row(self):
        # Regression test: PostgresTaskLedger explicitly sets conn.row_factory
        # to dict_row on every connection it borrows from the pool, and
        # psycopg_pool does not reset row_factory when a connection is
        # returned. A migration runner sharing the same pool (as
        # LiveAppState does) must not assume the default tuple row factory,
        # or it crashes with a KeyError the first time it reuses a
        # connection previously touched by the ledger.
        runner = PostgresMigrationRunner(
            self.pool,
            ROOT / "src" / "xingestion" / "migrations" / "postgres_sql",
        )
        runner.apply()

        ledger = PostgresTaskLedger(self.pool)
        # Exercise several ledger calls to make it likely (not just possible)
        # that a connection touched by dict_row is returned to the pool.
        for _ in range(5):
            ledger.task_state_counts()

        status = runner.status()

        self.assertTrue(status.current)
        self.assertEqual(status.applied_versions, EXPECTED_MIGRATIONS)


if __name__ == "__main__":
    unittest.main()
