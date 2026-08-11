from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class TelemetrySummary:
    total_attempts: int
    successes: int
    failures: int
    errors_by_class: dict[str, int]


@dataclass(frozen=True)
class ProtocolAttempt:
    attempt_id: int
    task_id: str
    capability_id: str
    release_id: str
    recipe_revision_id: str
    state: str
    session_id: str | None
    network_context: str | None
    error_class: str | None
    tweet_count: int
    next_cursor_present: bool
    duration_ms: int
    created_at: str


@dataclass(frozen=True)
class ReleaseErrorSignal:
    error_class: str
    count: int
    distinct_sessions: int


class ProtocolTelemetryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._initialize()

    def record_attempt(
        self,
        *,
        task_id: str,
        capability_id: str,
        release_id: str,
        recipe_revision_id: str,
        state: str,
        session_id: str | None,
        network_context: str | None = None,
        error_class: str | None = None,
        tweet_count: int = 0,
        next_cursor_present: bool = False,
        duration_ms: int = 0,
    ) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO protocol_attempts (
                    task_id,
                    capability_id,
                    release_id,
                    recipe_revision_id,
                    state,
                    session_id,
                    network_context,
                    error_class,
                    tweet_count,
                    next_cursor_present,
                    duration_ms,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    capability_id,
                    release_id,
                    recipe_revision_id,
                    state,
                    session_id,
                    network_context,
                    error_class,
                    tweet_count,
                    1 if next_cursor_present else 0,
                    duration_ms,
                    _now(),
                ),
            )
            conn.commit()

    def summary(self) -> TelemetrySummary:
        with closing(self._connect()) as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS count FROM protocol_attempts"
            ).fetchone()
            successes = conn.execute(
                "SELECT COUNT(*) AS count FROM protocol_attempts WHERE state = 'SUCCESS'"
            ).fetchone()
            failures = conn.execute(
                "SELECT COUNT(*) AS count FROM protocol_attempts WHERE state = 'FAILURE'"
            ).fetchone()
            error_rows = conn.execute(
                """
                SELECT error_class, COUNT(*) AS count
                FROM protocol_attempts
                WHERE error_class IS NOT NULL
                GROUP BY error_class
                ORDER BY count DESC, error_class ASC
                """
            ).fetchall()
        return TelemetrySummary(
            total_attempts=int(total["count"]),
            successes=int(successes["count"]),
            failures=int(failures["count"]),
            errors_by_class={
                row["error_class"]: int(row["count"])
                for row in error_rows
            },
        )

    def list_for_task(self, task_id: str) -> tuple[ProtocolAttempt, ...]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM protocol_attempts
                WHERE task_id = ?
                ORDER BY attempt_id ASC
                """,
                (task_id,),
            ).fetchall()
        return tuple(_attempt_from_row(row) for row in rows)

    def release_error_signals(self, release_id: str) -> tuple[ReleaseErrorSignal, ...]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT
                    error_class,
                    COUNT(*) AS count,
                    COUNT(DISTINCT session_id) AS distinct_sessions
                FROM protocol_attempts
                WHERE release_id = ?
                  AND error_class IS NOT NULL
                GROUP BY error_class
                ORDER BY count DESC, error_class ASC
                """,
                (release_id,),
            ).fetchall()
        return tuple(
            ReleaseErrorSignal(
                error_class=row["error_class"],
                count=int(row["count"]),
                distinct_sessions=int(row["distinct_sessions"]),
            )
            for row in rows
        )

    def _initialize(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS protocol_attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    release_id TEXT NOT NULL,
                    recipe_revision_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    session_id TEXT,
                    network_context TEXT,
                    error_class TEXT,
                    tweet_count INTEGER NOT NULL,
                    next_cursor_present INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_protocol_attempts_release_created
                ON protocol_attempts (release_id, created_at)
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _attempt_from_row(row: sqlite3.Row) -> ProtocolAttempt:
    return ProtocolAttempt(
        attempt_id=int(row["attempt_id"]),
        task_id=row["task_id"],
        capability_id=row["capability_id"],
        release_id=row["release_id"],
        recipe_revision_id=row["recipe_revision_id"],
        state=row["state"],
        session_id=row["session_id"],
        network_context=row["network_context"] if "network_context" in row.keys() else None,
        error_class=row["error_class"],
        tweet_count=int(row["tweet_count"]),
        next_cursor_present=bool(row["next_cursor_present"]),
        duration_ms=int(row["duration_ms"]),
        created_at=row["created_at"],
    )
