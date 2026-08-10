from __future__ import annotations

from dataclasses import dataclass

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
        )

        try:
            page = self._execute_task(task)
        except (ProtocolError, ValueError) as exc:
            task = self.ledger.transition_task(
                task.task_id,
                from_state=TaskState.RUNNING,
                to_state=TaskState.DEAD_LETTER,
            )
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
