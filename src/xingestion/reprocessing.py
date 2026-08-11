from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from uuid import uuid4

from xingestion.canonical import CanonicalStore
from xingestion.tasks import SQLiteTaskLedger, TaskState
from xingestion.xprotocol.evidence import RawEvidenceRef
from xingestion.xprotocol.runtime import parse_search_tweets_page


@dataclass(frozen=True)
class ReprocessResult:
    task_id: str
    raw_evidence_id: str
    parsed_tweets: int
    canonical_counts: dict[str, int]


@dataclass(frozen=True)
class ReprocessJob:
    job_id: str
    release_id: str
    state: str
    matched_tasks: int
    processed_tasks: int
    failed_tasks: int
    error_json: dict[str, str]
    created_at: str
    updated_at: str


class ReprocessJobStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._initialize()

    def run_for_release(
        self,
        *,
        release_id: str,
        ledger: SQLiteTaskLedger,
        canonical_store: CanonicalStore,
        limit: int = 100,
    ) -> ReprocessJob:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        job_id = f"reprocess-{uuid4().hex}"
        now = _now()
        task_ids = _completed_task_ids_for_release(ledger, release_id=release_id, limit=limit)
        self._insert_job(
            job_id=job_id,
            release_id=release_id,
            state="RUNNING",
            matched_tasks=len(task_ids),
            processed_tasks=0,
            failed_tasks=0,
            error_json={},
            now=now,
        )

        processed = 0
        failures: dict[str, str] = {}
        for task_id in task_ids:
            try:
                reprocess_task_evidence(
                    task_id=task_id,
                    ledger=ledger,
                    canonical_store=canonical_store,
                )
                processed += 1
            except Exception as exc:
                failures[task_id] = str(exc)

        state = "DONE" if not failures else "DONE_WITH_ERRORS"
        return self._finish_job(
            job_id=job_id,
            state=state,
            processed_tasks=processed,
            failed_tasks=len(failures),
            error_json=failures,
        )

    def get_job(self, job_id: str) -> ReprocessJob | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM reprocess_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return _job_from_row(row) if row else None

    def _insert_job(
        self,
        *,
        job_id: str,
        release_id: str,
        state: str,
        matched_tasks: int,
        processed_tasks: int,
        failed_tasks: int,
        error_json: dict[str, str],
        now: str,
    ) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO reprocess_jobs (
                    job_id,
                    release_id,
                    state,
                    matched_tasks,
                    processed_tasks,
                    failed_tasks,
                    error_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    release_id,
                    state,
                    matched_tasks,
                    processed_tasks,
                    failed_tasks,
                    json.dumps(error_json, sort_keys=True),
                    now,
                    now,
                ),
            )
            conn.commit()

    def _finish_job(
        self,
        *,
        job_id: str,
        state: str,
        processed_tasks: int,
        failed_tasks: int,
        error_json: dict[str, str],
    ) -> ReprocessJob:
        now = _now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE reprocess_jobs
                SET state = ?,
                    processed_tasks = ?,
                    failed_tasks = ?,
                    error_json = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (
                    state,
                    processed_tasks,
                    failed_tasks,
                    json.dumps(error_json, sort_keys=True),
                    now,
                    job_id,
                ),
            )
            conn.commit()
        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError("reprocess job could not be reloaded")
        return job

    def _initialize(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reprocess_jobs (
                    job_id TEXT PRIMARY KEY,
                    release_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    matched_tasks INTEGER NOT NULL,
                    processed_tasks INTEGER NOT NULL,
                    failed_tasks INTEGER NOT NULL,
                    error_json TEXT NOT NULL,
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


def reprocess_task_evidence(
    *,
    task_id: str,
    ledger: SQLiteTaskLedger,
    canonical_store: CanonicalStore,
) -> ReprocessResult:
    task = ledger.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    if task.state != TaskState.DONE or not task.result_json:
        raise ValueError("Only completed tasks with raw evidence can be reprocessed")

    raw = task.result_json.get("raw_evidence")
    if not isinstance(raw, dict):
        raise ValueError("Task result does not contain raw evidence")

    storage_uri = str(raw.get("storage_uri", ""))
    if not storage_uri:
        raise ValueError("Raw evidence storage URI is missing")

    payload = json.loads(Path(storage_uri).read_text(encoding="utf-8"))
    evidence = RawEvidenceRef(
        evidence_id=str(raw["evidence_id"]),
        content_sha256=str(raw["content_sha256"]),
        media_type="application/json",
        storage_uri=storage_uri,
        captured_at=task.updated_at,
        metadata={
            "reprocessed_from_task_id": task.task_id,
        },
    )
    page = parse_search_tweets_page(payload, raw_evidence_ref=evidence)
    canonical_store.ingest_search_tweets_page(
        page,
        task_id=task.task_id,
        release_id=str(task.plan_json["release_id"]),
        recipe_revision_id=str(task.plan_json["recipe_revision_id"]),
    )
    return ReprocessResult(
        task_id=task.task_id,
        raw_evidence_id=evidence.evidence_id,
        parsed_tweets=len(page.tweets),
        canonical_counts=canonical_store.counts(),
    )


def _completed_task_ids_for_release(
    ledger: SQLiteTaskLedger,
    *,
    release_id: str,
    limit: int,
) -> tuple[str, ...]:
    with closing(ledger._connect()) as conn:
        rows = conn.execute(
            """
            SELECT task_id
            FROM capability_tasks
            WHERE state = ?
              AND json_extract(plan_json, '$.release_id') = ?
              AND result_json IS NOT NULL
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (TaskState.DONE.value, release_id, limit),
        ).fetchall()
    return tuple(row["task_id"] for row in rows)


def _job_from_row(row: sqlite3.Row) -> ReprocessJob:
    return ReprocessJob(
        job_id=row["job_id"],
        release_id=row["release_id"],
        state=row["state"],
        matched_tasks=int(row["matched_tasks"]),
        processed_tasks=int(row["processed_tasks"]),
        failed_tasks=int(row["failed_tasks"]),
        error_json=json.loads(row["error_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
