from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


@dataclass(frozen=True)
class PostgresMigration:
    version: str
    path: Path


@dataclass(frozen=True)
class PostgresMigrationStatus:
    available_versions: tuple[str, ...]
    applied_versions: tuple[str, ...]
    pending_versions: tuple[str, ...]

    @property
    def current(self) -> bool:
        return not self.pending_versions


class PostgresMigrationRunner:
    def __init__(self, pool: ConnectionPool, migrations_dir: str | Path) -> None:
        self.pool = pool
        self.migrations_dir = Path(migrations_dir)

    def apply(self) -> tuple[str, ...]:
        applied: list[str] = []
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            self._ensure_migration_table(conn)
            existing = {
                row["version"]
                for row in conn.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            for migration in self._migrations():
                if migration.version in existing:
                    continue
                sql = migration.path.read_text(encoding="utf-8")
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (migration.version,),
                    )
                applied.append(migration.version)
        return tuple(applied)

    def applied_versions(self) -> tuple[str, ...]:
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            self._ensure_migration_table(conn)
            rows = conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        return tuple(row["version"] for row in rows)

    def status(self) -> PostgresMigrationStatus:
        available = tuple(migration.version for migration in self._migrations())
        applied = self.applied_versions()
        applied_set = set(applied)
        pending = tuple(version for version in available if version not in applied_set)
        return PostgresMigrationStatus(
            available_versions=available,
            applied_versions=applied,
            pending_versions=pending,
        )

    def require_current(self) -> PostgresMigrationStatus:
        status = self.status()
        if not status.current:
            joined = ", ".join(status.pending_versions)
            raise RuntimeError(
                f"Pending Postgres migrations: {joined}. Run run_postgres_migrations.py first."
            )
        return status

    def _migrations(self) -> tuple[PostgresMigration, ...]:
        paths = sorted(self.migrations_dir.glob("*.sql"))
        return tuple(
            PostgresMigration(path.stem.split("_", 1)[0], path) for path in paths
        )

    def _ensure_migration_table(self, conn: psycopg.Connection) -> None:
        with conn.transaction():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
