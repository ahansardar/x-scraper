from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool

from xingestion.migrations import PostgresMigrationRunner
from xingestion.tasks import PostgresTaskLedger

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_DSN = "postgresql://xingestion:xingestion@127.0.0.1:55432/xingestion"


def test_dsn() -> str:
    return os.getenv("XINGESTION_TEST_POSTGRES_DSN", DEFAULT_TEST_DSN)


def probe_reachable(dsn: str) -> None:
    # A single direct connect attempt fails on a refused connection far
    # faster than letting ConnectionPool's background retry/backoff loop
    # run out its full wait() timeout -- matters a lot when dozens of
    # tests share this fixture on a host with no Postgres at all (e.g. the
    # Windows CI job, which deliberately has no service containers).
    with psycopg.connect(dsn, connect_timeout=2) as conn:
        conn.execute("SELECT 1")


def make_postgres_ledger() -> PostgresTaskLedger:
    """Return a PostgresTaskLedger backed by a freshly-migrated, truncated database.

    Raises if Postgres is unreachable; callers should catch and skip.
    """
    dsn = test_dsn()
    probe_reachable(dsn)
    pool = ConnectionPool(
        dsn,
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
