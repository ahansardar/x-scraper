from __future__ import annotations

import os
from pathlib import Path

from psycopg_pool import ConnectionPool

from xingestion.migrations import PostgresMigrationRunner
from xingestion.tasks import PostgresTaskLedger

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_DSN = "postgresql://xingestion:xingestion@127.0.0.1:55432/xingestion"


def test_dsn() -> str:
    return os.getenv("XINGESTION_TEST_POSTGRES_DSN", DEFAULT_TEST_DSN)


def make_postgres_ledger() -> PostgresTaskLedger:
    """Return a PostgresTaskLedger backed by a freshly-migrated, truncated database.

    Raises if Postgres is unreachable; callers should catch and skip.
    """
    pool = ConnectionPool(
        test_dsn(),
        min_size=1,
        max_size=5,
        open=True,
        timeout=3,
        kwargs={"connect_timeout": 3},
    )
    try:
        pool.wait(timeout=5)
    except Exception:
        pool.close()
        raise
    runner = PostgresMigrationRunner(
        pool, ROOT / "src" / "xingestion" / "migrations" / "postgres_sql"
    )
    runner.apply()
    with pool.connection() as conn:
        conn.execute("TRUNCATE outbox_events, capability_tasks CASCADE")
        conn.commit()
    return PostgresTaskLedger(pool)
