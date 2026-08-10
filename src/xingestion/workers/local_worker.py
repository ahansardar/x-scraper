from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from xingestion.tasks import SQLiteTaskLedger, TaskState
from xrev.evidence import RawEvidenceRef, RawEvidenceSink
from xrev.protocol import CapabilityId, ProtocolReleaseManifest
from xrev.runtime import (
    ProtocolError,
    SearchTweetsRequest,
    WebSessionAuth,
    acquire_search_tweets_page,
)
from xrev.runtime.transport import OneAttemptTransport
from xrev.runtime.transport import RetryDisposition


@dataclass(frozen=True)
class WorkerResult:
    processed: bool
    task_id: str | None = None
    state: TaskState | None = None
    raw_evidence_ref: RawEvidenceRef | None = None
    error_class: str | None = None
    message: str | None = None


class LocalWorker:
    def __init__(
        self,
        *,
        ledger: SQLiteTaskLedger,
        manifest: ProtocolReleaseManifest,
        auth: WebSessionAuth,
        transport: OneAttemptTransport,
        raw_evidence_sink: RawEvidenceSink,
    ) -> None:
        self.ledger = ledger
        self.manifest = manifest
        self.auth = auth
        self.transport = transport
        self.raw_evidence_sink = raw_evidence_sink

    def process_one(self) -> WorkerResult:
        self.ledger.enqueue_due_retries()
        event = self.ledger.claim_next_outbox_event()
        if event is None:
            return WorkerResult(processed=False)

        task = self.ledger.get_task(event.task_id)
        if task is None:
            return WorkerResult(
                processed=True,
                task_id=event.task_id,
                error_class="TASK_NOT_FOUND",
                message="Outbox event referenced a missing task",
            )

        if task.state == TaskState.CREATED:
            task = self.ledger.transition_task(
                task.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.ENQUEUED,
            )

        if task.state != TaskState.ENQUEUED:
            return WorkerResult(
                processed=True,
                task_id=task.task_id,
                state=task.state,
                message="Task was already processed or not ready",
            )

        task = self.ledger.transition_task(
            task.task_id,
            from_state=TaskState.ENQUEUED,
            to_state=TaskState.RUNNING,
            increment_attempt=True,
        )

        try:
            page = self._execute_task(task)
        except (ProtocolError, ValueError) as exc:
            task = self._handle_failure(task, exc)
            return WorkerResult(
                processed=True,
                task_id=task.task_id,
                state=task.state,
                error_class=getattr(exc, "error_class", exc.__class__.__name__),
                message=str(exc),
            )

        task = self.ledger.transition_task(
            task.task_id,
            from_state=TaskState.RUNNING,
            to_state=TaskState.DONE,
            result_json={
                "raw_evidence": {
                    "evidence_id": page.raw_evidence_ref.evidence_id,
                    "content_sha256": page.raw_evidence_ref.content_sha256,
                    "storage_uri": page.raw_evidence_ref.storage_uri,
                }
            },
        )
        return WorkerResult(
            processed=True,
            task_id=task.task_id,
            state=task.state,
            raw_evidence_ref=page.raw_evidence_ref,
        )

    def _execute_task(self, task):
        if task.capability_id != CapabilityId.SEARCH_TWEETS:
            raise ValueError(f"Unsupported capability {task.capability_id.value}")

        recipe = self._recipe_for_task(task)
        payload = task.request_json["payload"]
        return acquire_search_tweets_page(
            recipe=recipe,
            auth=self.auth,
            request=SearchTweetsRequest(
                query=str(payload["query"]),
                product=str(payload.get("product", "Top")),
                count=int(payload.get("page_size", 20)),
                cursor=payload.get("cursor"),
            ),
            transport=self.transport,
            raw_evidence_sink=self.raw_evidence_sink,
        )

    def _recipe_for_task(self, task):
        recipe_revision_id = task.plan_json["recipe_revision_id"]
        for binding in self.manifest.bindings:
            if binding.recipe.revision_id == recipe_revision_id:
                return binding.recipe
        raise ValueError(f"No recipe for {recipe_revision_id}")

    def _handle_failure(self, task, exc):
        error_json = {
            "error_class": getattr(exc, "error_class", exc.__class__.__name__),
            "message": str(exc),
            "attempt_count": task.attempt_count,
        }
        retry_disposition = getattr(exc, "retry_disposition", RetryDisposition.NEVER)
        if (
            retry_disposition != RetryDisposition.NEVER
            and task.attempt_count < task.max_attempts
        ):
            retry_after = getattr(exc, "retry_after_seconds", None)
            delay_seconds = retry_after if retry_after is not None else _backoff_seconds(task.attempt_count)
            return self.ledger.transition_task(
                task.task_id,
                from_state=TaskState.RUNNING,
                to_state=TaskState.RETRY_SCHEDULED,
                error_json={
                    **error_json,
                    "retry_disposition": str(retry_disposition),
                    "retry_after_seconds": delay_seconds,
                },
                next_attempt_at=(datetime.now(UTC) + timedelta(seconds=delay_seconds)).isoformat(),
            )

        return self.ledger.transition_task(
            task.task_id,
            from_state=TaskState.RUNNING,
            to_state=TaskState.DEAD_LETTER,
            error_json={
                **error_json,
                "retry_disposition": str(retry_disposition),
            },
        )


def _backoff_seconds(attempt_count: int) -> int:
    return min(60, 2 ** max(0, attempt_count - 1))
