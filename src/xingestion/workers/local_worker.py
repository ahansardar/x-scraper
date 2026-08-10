from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from xingestion.tasks import SQLiteTaskLedger, TaskState
from xingestion.canonical import CanonicalStore
from xingestion.releases import ReleaseStore
from xingestion.capabilities import CapabilityPlanner, CapabilityRequest, SearchTweetsInput
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
from uuid import uuid4


@dataclass(frozen=True)
class WorkerResult:
    processed: bool
    task_id: str | None = None
    state: TaskState | None = None
    raw_evidence_ref: RawEvidenceRef | None = None
    error_class: str | None = None
    message: str | None = None
    lease_renewals: int = 0


class LocalWorker:
    def __init__(
        self,
        *,
        ledger: SQLiteTaskLedger,
        manifest: ProtocolReleaseManifest,
        auth: WebSessionAuth,
        transport: OneAttemptTransport,
        raw_evidence_sink: RawEvidenceSink,
        canonical_store: CanonicalStore | None = None,
        release_store: ReleaseStore | None = None,
        owner: str | None = None,
        lease_seconds: int = 300,
    ) -> None:
        self.ledger = ledger
        self.manifest = manifest
        self.auth = auth
        self.transport = transport
        self.raw_evidence_sink = raw_evidence_sink
        self.canonical_store = canonical_store
        self.release_store = release_store
        self.planner = CapabilityPlanner(self.manifest)
        self.owner = owner or f"worker-{uuid4().hex[:12]}"
        self.lease_seconds = lease_seconds

    def process_one(self) -> WorkerResult:
        self.ledger.enqueue_due_retries()
        self.ledger.recover_expired_leases()
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

        if self.release_store and not self.release_store.execution_allowed(self.manifest.release_id):
            task = self.ledger.transition_task(
                task.task_id,
                from_state=TaskState.ENQUEUED,
                to_state=TaskState.DEAD_LETTER,
                error_json={
                    "error_class": "PROTOCOL_RELEASE_BLOCKED",
                    "message": f"Protocol release {self.manifest.release_id} is not executable",
                    "release_id": self.manifest.release_id,
                },
            )
            return WorkerResult(
                processed=True,
                task_id=task.task_id,
                state=task.state,
                error_class="PROTOCOL_RELEASE_BLOCKED",
                message=f"Protocol release {self.manifest.release_id} is not executable",
            )

        lease_expires_at = (
            datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
        ).isoformat()
        task = self.ledger.acquire_execution_lease(
            task.task_id,
            owner=self.owner,
            lease_expires_at=lease_expires_at,
        )
        lease_renewals = 0

        try:
            task = self._renew_lease(task)
            lease_renewals += 1
            page = self._execute_task(task)
            task = self._renew_lease(task)
            lease_renewals += 1
        except (ProtocolError, ValueError) as exc:
            task = self._handle_failure(task, exc)
            return WorkerResult(
                processed=True,
                task_id=task.task_id,
                state=task.state,
                error_class=getattr(exc, "error_class", exc.__class__.__name__),
                message=str(exc),
                lease_renewals=lease_renewals,
            )

        if self.canonical_store is not None:
            self.canonical_store.ingest_search_tweets_page(
                page,
                task_id=task.task_id,
                release_id=self.manifest.release_id,
                recipe_revision_id=task.plan_json["recipe_revision_id"],
            )
        continuation_task_id = self._queue_continuation_if_needed(task, page)

        task = self.ledger.transition_task(
            task.task_id,
            from_state=TaskState.RUNNING,
            to_state=TaskState.DONE,
            lease_token=task.lease_token,
            delivery_generation=task.delivery_generation,
            clear_lease=True,
            result_json={
                "raw_evidence": {
                    "evidence_id": page.raw_evidence_ref.evidence_id,
                    "content_sha256": page.raw_evidence_ref.content_sha256,
                    "storage_uri": page.raw_evidence_ref.storage_uri,
                },
                "pagination": {
                    "next_cursor": page.next_cursor,
                    "page_number": int(task.request_json["payload"].get("page_number", 1)),
                    "max_pages": int(task.request_json["payload"].get("max_pages", 1)),
                    "continuation_task_id": continuation_task_id,
                },
            },
        )
        return WorkerResult(
            processed=True,
            task_id=task.task_id,
            state=task.state,
            raw_evidence_ref=page.raw_evidence_ref,
            lease_renewals=lease_renewals,
        )

    def _queue_continuation_if_needed(self, task, page):
        payload = task.request_json["payload"]
        page_number = int(payload.get("page_number", 1))
        max_pages = int(payload.get("max_pages", 1))
        if not page.next_cursor or page_number >= max_pages:
            return None

        root_task_id = payload.get("pagination_root_task_id") or task.task_id
        next_payload = SearchTweetsInput(
            query=str(payload["query"]),
            product=str(payload.get("product", "Top")),
            cursor=page.next_cursor,
            page_size=int(payload.get("page_size", 20)),
            max_pages=max_pages,
            page_number=page_number + 1,
            pagination_root_task_id=str(root_task_id),
            pagination_parent_task_id=task.task_id,
        )
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=task.contract_version,
            payload=next_payload,
        )
        plan = self.planner.plan(request)
        continuation = self.ledger.create_task(
            idempotency_key=f"pagination:{root_task_id}:{page_number + 1}",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        return continuation.task_id

    def _renew_lease(self, task):
        lease_expires_at = (
            datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
        ).isoformat()
        return self.ledger.renew_execution_lease(
            task.task_id,
            lease_token=task.lease_token,
            delivery_generation=task.delivery_generation,
            lease_expires_at=lease_expires_at,
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
                lease_token=task.lease_token,
                delivery_generation=task.delivery_generation,
                clear_lease=True,
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
            lease_token=task.lease_token,
            delivery_generation=task.delivery_generation,
            clear_lease=True,
            error_json={
                **error_json,
                "retry_disposition": str(retry_disposition),
            },
        )


def _backoff_seconds(attempt_count: int) -> int:
    return min(60, 2 ** max(0, attempt_count - 1))
