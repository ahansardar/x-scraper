from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Protocol

from xingestion.tasks import CapabilityTask, OutboxEvent, TaskLedger
from xingestion.workers import WorkerResult


@dataclass(frozen=True)
class OutboxQueueItem:
    event: OutboxEvent
    task: CapabilityTask | None
    age_seconds: int | None

    def public_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event.event_id,
            "task_id": self.event.task_id,
            "event_type": self.event.event_type,
            "payload": dict(self.event.payload_json),
            "created_at": self.event.created_at,
            "published_at": self.event.published_at,
            "age_seconds": self.age_seconds,
            "task_state": self.task.state.value if self.task else "MISSING",
            "task_updated_at": self.task.updated_at if self.task else None,
            "task_attempt_count": self.task.attempt_count if self.task else None,
            "task_max_attempts": self.task.max_attempts if self.task else None,
            "task_next_attempt_at": self.task.next_attempt_at if self.task else None,
        }


@dataclass(frozen=True)
class OutboxProcessResult:
    requested_limit: int
    processed_events: int
    before: dict[str, int | str | None]
    after: dict[str, int | str | None]
    worker_results: tuple[WorkerResult, ...]

    def public_dict(self) -> dict[str, object]:
        return {
            "requested_limit": self.requested_limit,
            "processed_events": self.processed_events,
            "before": dict(self.before),
            "after": dict(self.after),
            "worker_results": [
                _worker_result_dict(result) for result in self.worker_results
            ],
        }


class ProcessOneWorker(Protocol):
    def process_one(self) -> WorkerResult:
        ...


def list_outbox_queue(
    ledger: TaskLedger,
    *,
    limit: int = 25,
    now: str | None = None,
) -> dict[str, object]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    now = now or datetime.now(UTC).isoformat()
    items = [
        OutboxQueueItem(
            event=event,
            task=ledger.get_task(event.task_id),
            age_seconds=_age_seconds(now, event.created_at),
        )
        for event in ledger.list_unpublished_outbox_events(limit=limit)
    ]
    return {
        "stats": ledger.outbox_stats(),
        "events": [item.public_dict() for item in items],
        "limit": limit,
    }


def process_outbox(
    *,
    ledger: TaskLedger,
    worker: ProcessOneWorker,
    limit: int,
) -> OutboxProcessResult:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    before = ledger.outbox_stats()
    results: list[WorkerResult] = []
    for _ in range(limit):
        result = worker.process_one()
        if not result.processed:
            break
        results.append(result)
    return OutboxProcessResult(
        requested_limit=limit,
        processed_events=len(results),
        before=before,
        after=ledger.outbox_stats(),
        worker_results=tuple(results),
    )


def _age_seconds(now: str, created_at: str) -> int | None:
    try:
        return max(
            0,
            int(
                (
                    datetime.fromisoformat(now)
                    - datetime.fromisoformat(created_at)
                ).total_seconds()
            ),
        )
    except ValueError:
        return None


def _worker_result_dict(result: WorkerResult) -> dict[str, object]:
    return {
        "processed": result.processed,
        "task_id": result.task_id,
        "state": result.state.value if result.state else None,
        "error_class": result.error_class,
        "message": result.message,
        "lease_renewals": result.lease_renewals,
        "session_id": result.session_id,
        "raw_evidence": (
            {
                "evidence_id": result.raw_evidence_ref.evidence_id,
                "content_sha256": result.raw_evidence_ref.content_sha256,
                "storage_uri": result.raw_evidence_ref.storage_uri,
            }
            if result.raw_evidence_ref
            else None
        ),
    }
