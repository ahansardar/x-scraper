from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
import sqlite3


class ReleaseHealth(StrEnum):
    UNKNOWN = "UNKNOWN"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class ReleaseRecord:
    release_id: str
    health: ReleaseHealth
    reason: str
    updated_at: str


class ReleaseStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._initialize()

    def ensure_release(
        self,
        release_id: str,
        *,
        health: ReleaseHealth = ReleaseHealth.ACTIVE,
        reason: str = "bootstrapped",
    ) -> ReleaseRecord:
        existing = self.get_release(release_id)
        if existing:
            return existing
        return self.set_health(release_id, health=health, reason=reason)

    def set_health(
        self,
        release_id: str,
        *,
        health: ReleaseHealth,
        reason: str,
    ) -> ReleaseRecord:
        if not release_id.strip():
            raise ValueError("release_id cannot be empty")
        now = _now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO protocol_release_health (
                    release_id,
                    health,
                    reason,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(release_id) DO UPDATE SET
                    health = excluded.health,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (release_id, health.value, reason, now),
            )
            conn.commit()
        release = self.get_release(release_id)
        if release is None:
            raise RuntimeError("release could not be reloaded")
        return release

    def get_release(self, release_id: str) -> ReleaseRecord | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM protocol_release_health WHERE release_id = ?",
                (release_id,),
            ).fetchone()
        return _release_from_row(row) if row else None

    def execution_allowed(self, release_id: str) -> bool:
        release = self.ensure_release(release_id)
        return release.health not in {ReleaseHealth.QUARANTINED, ReleaseHealth.RETIRED}

    def approve_release(self, release_id: str, *, reason: str = "approved") -> ReleaseRecord:
        release = self.ensure_release(release_id)
        now = _now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO approved_protocol_release (
                    id,
                    release_id,
                    reason,
                    updated_at
                )
                VALUES ('current', ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    release_id = excluded.release_id,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (release.release_id, reason, now),
            )
            conn.commit()
        return release

    def approved_release_id(self) -> str | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT release_id FROM approved_protocol_release WHERE id = 'current'"
            ).fetchone()
        return str(row["release_id"]) if row else None

    def _initialize(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS protocol_release_health (
                    release_id TEXT PRIMARY KEY,
                    health TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approved_protocol_release (
                    id TEXT PRIMARY KEY,
                    release_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _release_from_row(row: sqlite3.Row) -> ReleaseRecord:
    return ReleaseRecord(
        release_id=row["release_id"],
        health=ReleaseHealth(row["health"]),
        reason=row["reason"],
        updated_at=row["updated_at"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
