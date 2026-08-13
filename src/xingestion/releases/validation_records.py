from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
import uuid

from xingestion import __version__ as RUNTIME_VERSION
from xingestion.xprotocol.protocol import ProtocolReleaseManifest


@dataclass(frozen=True)
class RecipeValidationRecord:
    record_id: str
    release_id: str
    recipe_revision_id: str
    composition_hash: str
    runtime_version: str
    validation_type: str
    ok: bool
    summary: str
    created_at: str

    def public_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "release_id": self.release_id,
            "recipe_revision_id": self.recipe_revision_id,
            "composition_hash": self.composition_hash,
            "runtime_version": self.runtime_version,
            "validation_type": self.validation_type,
            "ok": self.ok,
            "summary": self.summary,
            "created_at": self.created_at,
        }


class RecipeValidationStore:
    """Persists first-class, release-bound recipe validation records.

    Complements the JSON validation-report artifacts in `protocol_validation.py`
    with a queryable history keyed by release_id/recipe_revision_id, so "was this
    exact recipe composition ever validated, and did it pass" is a lookup rather
    than a report-directory scan.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._initialize()

    def record_validation(
        self,
        *,
        release_id: str,
        recipe_revision_id: str,
        composition_hash: str,
        validation_type: str,
        ok: bool,
        summary: str,
        runtime_version: str = RUNTIME_VERSION,
    ) -> RecipeValidationRecord:
        if not release_id.strip():
            raise ValueError("release_id cannot be empty")
        if not recipe_revision_id.strip():
            raise ValueError("recipe_revision_id cannot be empty")
        if not validation_type.strip():
            raise ValueError("validation_type cannot be empty")
        record = RecipeValidationRecord(
            record_id=uuid.uuid4().hex,
            release_id=release_id,
            recipe_revision_id=recipe_revision_id,
            composition_hash=composition_hash,
            runtime_version=runtime_version,
            validation_type=validation_type.strip().upper(),
            ok=ok,
            summary=summary,
            created_at=_now(),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO recipe_validation_record (
                    record_id, release_id, recipe_revision_id, composition_hash,
                    runtime_version, validation_type, ok, summary, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_id,
                    record.release_id,
                    record.recipe_revision_id,
                    record.composition_hash,
                    record.runtime_version,
                    record.validation_type,
                    1 if record.ok else 0,
                    record.summary,
                    record.created_at,
                ),
            )
            conn.commit()
        return record

    def list_recent(
        self,
        *,
        release_id: str | None = None,
        recipe_revision_id: str | None = None,
        limit: int = 25,
    ) -> tuple[RecipeValidationRecord, ...]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        clauses = []
        params: list[object] = []
        if release_id is not None:
            clauses.append("release_id = ?")
            params.append(release_id)
        if recipe_revision_id is not None:
            clauses.append("recipe_revision_id = ?")
            params.append(recipe_revision_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM recipe_validation_record
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def latest_for_recipe(
        self,
        *,
        release_id: str,
        recipe_revision_id: str,
        validation_type: str | None = None,
    ) -> RecipeValidationRecord | None:
        clauses = ["release_id = ?", "recipe_revision_id = ?"]
        params: list[object] = [release_id, recipe_revision_id]
        if validation_type is not None:
            clauses.append("validation_type = ?")
            params.append(validation_type.strip().upper())
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"""
                SELECT * FROM recipe_validation_record
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        return _record_from_row(row) if row else None

    def _initialize(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recipe_validation_record (
                    record_id TEXT PRIMARY KEY,
                    release_id TEXT NOT NULL,
                    recipe_revision_id TEXT NOT NULL,
                    composition_hash TEXT NOT NULL,
                    runtime_version TEXT NOT NULL,
                    validation_type TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_recipe_validation_record_release_recipe
                ON recipe_validation_record (release_id, recipe_revision_id, created_at)
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


@dataclass(frozen=True)
class RecipeValidationFreshness:
    recipe_revision_id: str
    composition_hash: str
    validation_type: str
    fresh: bool
    reason: str
    latest_record: RecipeValidationRecord | None

    def public_dict(self) -> dict[str, object]:
        return {
            "recipe_revision_id": self.recipe_revision_id,
            "composition_hash": self.composition_hash,
            "validation_type": self.validation_type,
            "fresh": self.fresh,
            "reason": self.reason,
            "latest_record": self.latest_record.public_dict() if self.latest_record else None,
        }


def recipe_validation_freshness(
    *,
    store: RecipeValidationStore,
    manifest: ProtocolReleaseManifest,
    validation_types: tuple[str, ...] = ("FIXTURE", "CAPTURE_REPLAY"),
) -> tuple[RecipeValidationFreshness, ...]:
    """Flag recipes whose live composition has drifted from what was last validated.

    A recipe's `recipe_revision_id` is a human-assigned label; its
    `composition_hash` is a computed content hash of the parser/operation/
    pagination/etc. revisions actually in effect. If someone edits a manifest's
    recipe composition without also bumping `recipe_revision_id`, the most
    recent validation record for that revision id silently stops describing
    what's actually running -- this catches that drift so it can prompt a
    fresh validation run instead of trusting stale results.
    """
    results = []
    for binding in manifest.bindings:
        recipe = binding.recipe
        for validation_type in validation_types:
            latest = store.latest_for_recipe(
                release_id=manifest.release_id,
                recipe_revision_id=recipe.revision_id,
                validation_type=validation_type,
            )
            if latest is None:
                fresh, reason = False, "no validation record found for this recipe revision"
            elif latest.composition_hash != recipe.composition_hash:
                fresh, reason = False, (
                    "recipe composition changed since the last validation record "
                    f"(validated={latest.composition_hash}, current={recipe.composition_hash})"
                )
            elif not latest.ok:
                fresh, reason = False, "most recent validation record for this composition failed"
            else:
                fresh, reason = True, "latest validation record matches current composition and passed"
            results.append(
                RecipeValidationFreshness(
                    recipe_revision_id=recipe.revision_id,
                    composition_hash=recipe.composition_hash,
                    validation_type=validation_type,
                    fresh=fresh,
                    reason=reason,
                    latest_record=latest,
                )
            )
    return tuple(results)


def record_recipe_validation_results(
    *,
    store: RecipeValidationStore,
    manifest: ProtocolReleaseManifest,
    results: tuple[tuple[str, bool, str], ...],
) -> tuple[RecipeValidationRecord, ...]:
    """Persist one record per (capability binding recipe x validation type).

    `results` is `(validation_type, ok, summary)` tuples from whichever
    validation reports the caller already built (fixture validation,
    capture/replay comparison, ...) -- kept decoupled from those report
    dataclasses so this module doesn't need to import them.
    """
    records = []
    for binding in manifest.bindings:
        for validation_type, ok, summary in results:
            records.append(
                store.record_validation(
                    release_id=manifest.release_id,
                    recipe_revision_id=binding.recipe.revision_id,
                    composition_hash=binding.recipe.composition_hash,
                    validation_type=validation_type,
                    ok=ok,
                    summary=summary,
                )
            )
    return tuple(records)


def _record_from_row(row: sqlite3.Row) -> RecipeValidationRecord:
    return RecipeValidationRecord(
        record_id=row["record_id"],
        release_id=row["release_id"],
        recipe_revision_id=row["recipe_revision_id"],
        composition_hash=row["composition_hash"],
        runtime_version=row["runtime_version"],
        validation_type=row["validation_type"],
        ok=bool(row["ok"]),
        summary=row["summary"],
        created_at=row["created_at"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
