from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg_pool import ConnectionPool

from xingestion.migrations import PostgresMigrationRunner
from xingestion.tasks import PostgresTaskLedger

ROOT = Path(__file__).resolve().parents[1]
# A dedicated database, deliberately NOT "xingestion" -- that's
# XINGESTION_POSTGRES_DSN's default, the same database a local `run_all.ps1`
# dev stack uses. make_postgres_ledger() TRUNCATEs capability_tasks/
# outbox_events on every call; sharing a database with a live stack meant
# running the test suite locally silently wiped its task/outbox history.
# CI is unaffected: its workflow always sets XINGESTION_TEST_POSTGRES_DSN
# explicitly, so this default is a local-only concern.
DEFAULT_TEST_DSN = "postgresql://xingestion:xingestion@127.0.0.1:55432/xingestion_test"


def test_dsn() -> str:
    return os.getenv("XINGESTION_TEST_POSTGRES_DSN", DEFAULT_TEST_DSN)


def _admin_dsn(dsn: str) -> str:
    """Same server/credentials as `dsn`, pointed at the always-present `postgres` database."""
    parts = urlsplit(dsn)
    return urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))


def _database_name(dsn: str) -> str:
    return urlsplit(dsn).path.lstrip("/")


def _create_database_if_missing(dsn: str) -> None:
    database = _database_name(dsn)
    with psycopg.connect(_admin_dsn(dsn), connect_timeout=2, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{database}"')


def probe_reachable(dsn: str) -> None:
    # A single direct connect attempt fails on a refused connection far
    # faster than letting ConnectionPool's background retry/backoff loop
    # run out its full wait() timeout -- matters a lot when dozens of
    # tests share this fixture on a host with no Postgres at all (e.g. the
    # Windows CI job, which deliberately has no service containers).
    try:
        with psycopg.connect(dsn, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
    except psycopg.OperationalError as exc:
        if "does not exist" not in str(exc):
            # Genuinely unreachable (connection refused, auth failure,
            # etc.) -- not a missing-database situation this can fix.
            raise
        _create_database_if_missing(dsn)
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
