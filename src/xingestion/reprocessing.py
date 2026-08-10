from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from xingestion.canonical import CanonicalStore
from xingestion.tasks import SQLiteTaskLedger, TaskState
from xrev.evidence import RawEvidenceRef
from xrev.runtime import parse_search_tweets_page


@dataclass(frozen=True)
class ReprocessResult:
    task_id: str
    raw_evidence_id: str
    parsed_tweets: int
    canonical_counts: dict[str, int]


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
