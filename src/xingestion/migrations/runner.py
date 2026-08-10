from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path


@dataclass(frozen=True)
class MigrationStatus:
    available_versions: tuple[str, ...]
    applied_versions: tuple[str, ...]
    pending_versions: tuple[str, ...]

    @property
    def current(self) -> bool:
        return not self.pending_versions


class MigrationRunner:
    def __init__(self, db_path: str | Path, migrations_dir: str | Path) -> None:
        self.db_path = Path(db_path)
        self.migrations_dir = Path(migrations_dir)

    def apply(self) -> tuple[str, ...]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        applied: list[str] = []
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            self._ensure_migration_table(conn)
            existing = {
                row["version"]
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for migration in self._migrations():
                if migration.version in existing:
                    continue
                sql = migration.path.read_text(encoding="utf-8")
                conn.execute("BEGIN")
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)",
                    (migration.version,),
                )
                conn.commit()
                applied.append(migration.version)
        return tuple(applied)

    def applied_versions(self) -> tuple[str, ...]:
        if not self.db_path.exists():
            return ()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            self._ensure_migration_table(conn)
            rows = conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        return tuple(row["version"] for row in rows)

    def status(self) -> MigrationStatus:
        available = tuple(migration.version for migration in self._migrations())
        applied = self.applied_versions()
        applied_set = set(applied)
        pending = tuple(version for version in available if version not in applied_set)
        return MigrationStatus(
            available_versions=available,
            applied_versions=applied,
            pending_versions=pending,
        )

    def require_current(self) -> MigrationStatus:
        status = self.status()
        if not status.current:
            joined = ", ".join(status.pending_versions)
            raise RuntimeError(f"Pending database migrations: {joined}. Run run_migrations.py first.")
        return status

    def _migrations(self) -> tuple[Migration, ...]:
        paths = sorted(self.migrations_dir.glob("*.sql"))
        return tuple(Migration(path.stem.split("_", 1)[0], path) for path in paths)

    def _ensure_migration_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
