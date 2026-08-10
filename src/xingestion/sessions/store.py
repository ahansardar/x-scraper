from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
import sqlite3
from uuid import uuid4


class SessionHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    CHALLENGED = "CHALLENGED"
    LOCKED = "LOCKED"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    account_label: str
    credential_ref: str
    network_context: str
    health: SessionHealth
    lease_owner: str | None
    lease_token: str | None
    lease_expires_at: str | None
    cooldown_until: str | None
    attempt_count: int
    success_count: int
    failure_count: int
    last_attempt_at: str | None
    last_success_at: str | None
    last_error_class: str | None
    last_error_message: str | None
    created_at: str
    updated_at: str


class SessionStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._initialize()

    def upsert_session(
        self,
        *,
        session_id: str,
        account_label: str,
        credential_ref: str,
        network_context: str = "direct",
        health: SessionHealth = SessionHealth.HEALTHY,
    ) -> SessionRecord:
        if not session_id.strip():
            raise ValueError("session_id cannot be empty")
        if credential_ref.startswith(("auth_token=", "ct0=", "Bearer ")):
            raise ValueError("credential_ref must be a secret reference, not raw secret material")

        now = _now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO session_artifacts (
                    session_id,
                    account_label,
                    credential_ref,
                    network_context,
                    health,
                    lease_owner,
                    lease_token,
                    lease_expires_at,
                    cooldown_until,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    account_label = excluded.account_label,
                    credential_ref = excluded.credential_ref,
                    network_context = excluded.network_context,
                    health = excluded.health,
                    cooldown_until = CASE
                        WHEN excluded.health = ?
                        THEN NULL
                        ELSE session_artifacts.cooldown_until
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    account_label,
                    credential_ref,
                    network_context,
                    health.value,
                    now,
                    now,
                    SessionHealth.HEALTHY.value,
                ),
            )
            conn.commit()
        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError("session could not be reloaded")
        return session

    def acquire_session(
        self,
        *,
        owner: str,
        lease_seconds: int = 300,
    ) -> SessionRecord | None:
        now = _now()
        expires = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
        token = f"session-lease-{uuid4().hex}"
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT *
                FROM session_artifacts
                WHERE (
                    health = ?
                    OR (
                        health = ?
                        AND cooldown_until IS NOT NULL
                        AND cooldown_until <= ?
                    )
                  )
                  AND (
                    cooldown_until IS NULL
                    OR cooldown_until <= ?
                  )
                  AND (
                    lease_token IS NULL
                    OR lease_expires_at IS NULL
                    OR lease_expires_at <= ?
                  )
                ORDER BY updated_at ASC
                LIMIT 1
                """,
                (SessionHealth.HEALTHY.value, SessionHealth.DEGRADED.value, now, now, now),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                """
                UPDATE session_artifacts
                SET lease_owner = ?,
                    lease_token = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (owner, token, expires, now, row["session_id"]),
            )
            conn.commit()

        return self.get_session(row["session_id"])

    def release_session(self, session_id: str, lease_token: str) -> None:
        now = _now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE session_artifacts
                SET lease_owner = NULL,
                    lease_token = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE session_id = ?
                  AND lease_token = ?
                """,
                (now, session_id, lease_token),
            )
            conn.commit()

    def update_health(
        self,
        session_id: str,
        *,
        health: SessionHealth,
        reason: str,
        cooldown_until: str | None = None,
    ) -> SessionRecord:
        now = _now()
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                UPDATE session_artifacts
                SET health = ?,
                    cooldown_until = ?,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (health.value, cooldown_until, now, session_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Session {session_id} not found")
            conn.commit()

        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError("updated session could not be reloaded")
        return session

    def record_attempt_started(self, session_id: str) -> SessionRecord:
        now = _now()
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                UPDATE session_artifacts
                SET attempt_count = attempt_count + 1,
                    last_attempt_at = ?,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (now, now, session_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Session {session_id} not found")
            conn.commit()
        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError("updated session could not be reloaded")
        return session

    def record_attempt_success(self, session_id: str) -> SessionRecord:
        now = _now()
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                UPDATE session_artifacts
                SET success_count = success_count + 1,
                    last_success_at = ?,
                    last_error_class = NULL,
                    last_error_message = NULL,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (now, now, session_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Session {session_id} not found")
            conn.commit()
        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError("updated session could not be reloaded")
        return session

    def record_attempt_failure(
        self,
        session_id: str,
        *,
        error_class: str,
        error_message: str,
    ) -> SessionRecord:
        now = _now()
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                UPDATE session_artifacts
                SET failure_count = failure_count + 1,
                    last_error_class = ?,
                    last_error_message = ?,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (error_class, _shorten(error_message), now, session_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Session {session_id} not found")
            conn.commit()
        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError("updated session could not be reloaded")
        return session

    def list_sessions(self) -> tuple[SessionRecord, ...]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM session_artifacts ORDER BY updated_at DESC"
            ).fetchall()
        return tuple(_session_from_row(row) for row in rows)

    def get_session(self, session_id: str) -> SessionRecord | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM session_artifacts WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return _session_from_row(row) if row else None

    def _initialize(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_artifacts (
                    session_id TEXT PRIMARY KEY,
                    account_label TEXT NOT NULL,
                    credential_ref TEXT NOT NULL,
                    network_context TEXT NOT NULL,
                    health TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_token TEXT,
                    lease_expires_at TEXT,
                    cooldown_until TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    last_attempt_at TEXT,
                    last_success_at TEXT,
                    last_error_class TEXT,
                    last_error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        session_id=row["session_id"],
        account_label=row["account_label"],
        credential_ref=row["credential_ref"],
        network_context=row["network_context"],
        health=SessionHealth(row["health"]),
        lease_owner=row["lease_owner"],
        lease_token=row["lease_token"],
        lease_expires_at=row["lease_expires_at"],
        cooldown_until=row["cooldown_until"],
        attempt_count=int(row["attempt_count"]),
        success_count=int(row["success_count"]),
        failure_count=int(row["failure_count"]),
        last_attempt_at=row["last_attempt_at"],
        last_success_at=row["last_success_at"],
        last_error_class=row["last_error_class"],
        last_error_message=row["last_error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _shorten(value: str, limit: int = 500) -> str:
    return value if len(value) <= limit else value[: limit - 3] + "..."
