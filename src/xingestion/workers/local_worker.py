from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from time import monotonic

from xingestion.tasks import SQLiteTaskLedger, TaskState
from xingestion.canonical import CanonicalStore
from xingestion.errors import RuntimeErrorEnvelope, classify_error, classify_exception
from xingestion.releases import ReleaseStore
from xingestion.secrets import SecretProvider
from xingestion.sessions import SessionHealth, SessionStore
from xingestion.capabilities import CapabilityPlanner, CapabilityRequest, SearchTweetsInput
from xingestion.telemetry import ProtocolTelemetryStore
from xingestion.xprotocol.evidence import RawEvidenceRef, RawEvidenceSink
from xingestion.xprotocol.protocol import CapabilityId, ProtocolReleaseManifest
from xingestion.xprotocol.runtime import (
    ProtocolError,
    SearchTweetsRequest,
    WebSessionAuth,
    acquire_search_tweets_page,
    validate_search_tweets_pagination,
)
from xingestion.xprotocol.runtime.transport import OneAttemptTransport
from xingestion.xprotocol.runtime.transport import RetryDisposition
from uuid import uuid4


LOGGER = logging.getLogger("xingestion.worker.local")
LOGGER.addHandler(logging.NullHandler())


@dataclass(frozen=True)
class WorkerResult:
    processed: bool
    task_id: str | None = None
    state: TaskState | None = None
    raw_evidence_ref: RawEvidenceRef | None = None
    error_class: str | None = None
    message: str | None = None
    lease_renewals: int = 0
    session_id: str | None = None
    network_context: str | None = None


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
        session_store: SessionStore | None = None,
        telemetry_store: ProtocolTelemetryStore | None = None,
        secret_provider: SecretProvider | None = None,
        required_network_context: str | None = None,
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
        self.session_store = session_store
        self.telemetry_store = telemetry_store
        self.secret_provider = secret_provider
        self.required_network_context = required_network_context
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
            envelope = classify_error(
                "TASK_NOT_FOUND",
                message="Outbox event referenced a missing task",
            )
            LOGGER.error("worker task missing %s", envelope.log_fields())
            return WorkerResult(
                processed=True,
                task_id=event.task_id,
                error_class=envelope.error_class,
                message=envelope.message,
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

        task_release_id = str(task.plan_json.get("release_id") or "")
        if task_release_id != self.manifest.release_id:
            envelope = classify_error(
                "PROTOCOL_RELEASE_MISMATCH",
                message=(
                    f"Task release {task_release_id or 'unknown'} does not match "
                    f"approved release {self.manifest.release_id}"
                ),
            )
            task = self.ledger.transition_task(
                task.task_id,
                from_state=TaskState.ENQUEUED,
                to_state=TaskState.DEAD_LETTER,
                error_json={
                    "error_class": envelope.error_class,
                    "message": envelope.message,
                    "runtime_error": envelope.public_dict(),
                    "task_release_id": task_release_id,
                    "approved_release_id": self.manifest.release_id,
                },
            )
            LOGGER.error(
                "worker release mismatch task=%s %s",
                task.task_id,
                envelope.log_fields(),
            )
            return WorkerResult(
                processed=True,
                task_id=task.task_id,
                state=task.state,
                error_class=envelope.error_class,
                message=envelope.message,
            )

        if self.release_store and not self.release_store.execution_allowed(self.manifest.release_id):
            envelope = classify_error(
                "PROTOCOL_RELEASE_BLOCKED",
                message=f"Protocol release {self.manifest.release_id} is not executable",
            )
            task = self.ledger.transition_task(
                task.task_id,
                from_state=TaskState.ENQUEUED,
                to_state=TaskState.DEAD_LETTER,
                error_json={
                    "error_class": envelope.error_class,
                    "message": envelope.message,
                    "runtime_error": envelope.public_dict(),
                    "release_id": self.manifest.release_id,
                },
            )
            LOGGER.error(
                "worker release blocked task=%s %s",
                task.task_id,
                envelope.log_fields(),
            )
            return WorkerResult(
                processed=True,
                task_id=task.task_id,
                state=task.state,
                error_class=envelope.error_class,
                message=envelope.message,
            )

        session = None
        if self.session_store is not None:
            session = self.session_store.acquire_session(
                owner=self.owner,
                lease_seconds=self.lease_seconds,
                required_network_context=self.required_network_context,
            )
            if session is None:
                message = "No healthy session lease is available"
                if self.required_network_context:
                    message = (
                        "No healthy session lease is available for network_context="
                        f"{self.required_network_context}"
                    )
                envelope = classify_error(
                    "SESSION_UNAVAILABLE",
                    message=message,
                )
                scheduled = self.ledger.transition_task(
                    task.task_id,
                    from_state=TaskState.ENQUEUED,
                    to_state=TaskState.RETRY_SCHEDULED,
                    error_json={
                        "error_class": envelope.error_class,
                        "message": envelope.message,
                        "runtime_error": envelope.public_dict(),
                    },
                    next_attempt_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
                )
                LOGGER.warning(
                    "worker session unavailable task=%s %s",
                    scheduled.task_id,
                    envelope.log_fields(),
                )
                return WorkerResult(
                    processed=True,
                    task_id=scheduled.task_id,
                    state=scheduled.state,
                    error_class=envelope.error_class,
                    message=envelope.message,
                    network_context=self.required_network_context,
                )

        auth = self.auth
        if session is not None and self.secret_provider is not None:
            try:
                auth = self.secret_provider.resolve_web_session_auth(session.credential_ref)
                missing = auth.missing_fields()
                if missing:
                    raise ValueError(
                        f"session credential reference is missing fields={','.join(missing)}"
                    )
            except ValueError as exc:
                envelope = classify_error(
                    "AUTH_OR_SESSION_REJECTED",
                    message=str(exc),
                    scope_hint="SESSION",
                )
                if self.session_store is not None:
                    self.session_store.update_health(
                        session.session_id,
                        health=SessionHealth.AUTH_EXPIRED,
                        reason="credential_resolution_failed",
                    )
                    self.session_store.record_attempt_failure(
                        session.session_id,
                        error_class=envelope.error_class,
                        error_message=envelope.message,
                    )
                scheduled = self.ledger.transition_task(
                    task.task_id,
                    from_state=TaskState.ENQUEUED,
                    to_state=TaskState.RETRY_SCHEDULED,
                    error_json={
                        "error_class": envelope.error_class,
                        "message": envelope.message,
                        "runtime_error": envelope.public_dict(),
                    },
                    next_attempt_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
                )
                LOGGER.warning(
                    "worker credential resolution failed task=%s session=%s %s",
                    scheduled.task_id,
                    session.session_id,
                    envelope.log_fields(),
                )
                if session.lease_token and self.session_store is not None:
                    self.session_store.release_session(
                        session.session_id,
                        session.lease_token,
                    )
                return WorkerResult(
                    processed=True,
                    task_id=scheduled.task_id,
                    state=scheduled.state,
                    error_class=envelope.error_class,
                    message=envelope.message,
                    session_id=session.session_id,
                    network_context=session.network_context,
                )

        lease_expires_at = (
            datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
        ).isoformat()
        lease_renewals = 0
        started = monotonic()

        try:
            task = self.ledger.acquire_execution_lease(
                task.task_id,
                owner=self.owner,
                lease_expires_at=lease_expires_at,
            )
            task = self._renew_lease(task)
            lease_renewals += 1
            if session is not None and self.session_store is not None:
                session = self.session_store.record_attempt_started(session.session_id)
            page = self._execute_task(task, auth=auth)
            task = self._renew_lease(task)
            lease_renewals += 1
            validated_next_cursor = self._validate_page_pagination(task, page)

            if session is not None and self.session_store is not None:
                session = self.session_store.record_attempt_success(session.session_id)

            if (
                session is not None
                and self.session_store is not None
                and session.health == SessionHealth.DEGRADED
            ):
                session = self.session_store.update_health(
                    session.session_id,
                    health=SessionHealth.HEALTHY,
                    reason="successful acquisition after cooldown",
                )

            if self.canonical_store is not None:
                self.canonical_store.ingest_search_tweets_page(
                    page,
                    task_id=task.task_id,
                    release_id=self.manifest.release_id,
                    recipe_revision_id=task.plan_json["recipe_revision_id"],
                )
            continuation_task_id = self._queue_continuation_if_needed(
                task,
                page,
                next_cursor=validated_next_cursor,
            )
            self._record_telemetry(
                task=task,
                session_id=session.session_id if session else None,
                network_context=session.network_context if session else None,
                state="SUCCESS",
                tweet_count=len(page.tweets),
                next_cursor_present=bool(validated_next_cursor),
                duration_ms=_duration_ms(started),
            )

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
                        "next_cursor": validated_next_cursor,
                        "page_number": int(task.request_json["payload"].get("page_number", 1)),
                        "max_pages": int(task.request_json["payload"].get("max_pages", 1)),
                        "continuation_task_id": continuation_task_id,
                    },
                    "session": {
                        "session_id": session.session_id if session else None,
                        "network_context": session.network_context if session else None,
                        "network_policy": (
                            session.network_policy.public_dict() if session else None
                        ),
                    },
                },
            )
            return WorkerResult(
                processed=True,
                task_id=task.task_id,
                state=task.state,
                raw_evidence_ref=page.raw_evidence_ref,
                lease_renewals=lease_renewals,
                session_id=session.session_id if session else None,
                network_context=session.network_context if session else None,
            )
        except (ProtocolError, ValueError) as exc:
            envelope = classify_exception(exc)
            if session is not None and isinstance(exc, ProtocolError):
                self._update_session_health_from_error(session.session_id, exc)
            if session is not None and self.session_store is not None:
                self.session_store.record_attempt_failure(
                    session.session_id,
                    error_class=envelope.error_class,
                    error_message=envelope.message,
                )
            self._record_telemetry(
                task=task,
                session_id=session.session_id if session else None,
                network_context=session.network_context if session else self.required_network_context,
                state="FAILURE",
                error_class=envelope.error_class,
                duration_ms=_duration_ms(started),
            )
            task = self._handle_failure(task, exc, envelope=envelope)
            LOGGER.error(
                "worker task failed task=%s state=%s session=%s %s",
                task.task_id,
                task.state.value,
                session.session_id if session else None,
                envelope.log_fields(),
            )
            return WorkerResult(
                processed=True,
                task_id=task.task_id,
                state=task.state,
                error_class=envelope.error_class,
                message=envelope.message,
                lease_renewals=lease_renewals,
                session_id=session.session_id if session else None,
                network_context=session.network_context if session else self.required_network_context,
            )
        finally:
            if session is not None and session.lease_token:
                self.session_store.release_session(session.session_id, session.lease_token)

    def _record_telemetry(
        self,
        *,
        task,
        session_id: str | None,
        network_context: str | None,
        state: str,
        error_class: str | None = None,
        tweet_count: int = 0,
        next_cursor_present: bool = False,
        duration_ms: int = 0,
    ) -> None:
        if self.telemetry_store is None:
            return
        self.telemetry_store.record_attempt(
            task_id=task.task_id,
            capability_id=task.capability_id.value,
            release_id=self.manifest.release_id,
            recipe_revision_id=str(task.plan_json["recipe_revision_id"]),
            state=state,
            session_id=session_id,
            network_context=network_context,
            error_class=error_class,
            tweet_count=tweet_count,
            next_cursor_present=next_cursor_present,
            duration_ms=duration_ms,
        )

    def _queue_continuation_if_needed(self, task, page, *, next_cursor: str | None):
        payload = task.request_json["payload"]
        page_number = int(payload.get("page_number", 1))
        max_pages = int(payload.get("max_pages", 1))
        if not next_cursor or page_number >= max_pages:
            return None

        root_task_id = payload.get("pagination_root_task_id") or task.task_id
        next_payload = SearchTweetsInput(
            query=str(payload["query"]),
            product=str(payload.get("product", "Top")),
            cursor=next_cursor,
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

    def _validate_page_pagination(self, task, page) -> str | None:
        payload = task.request_json["payload"]
        page_number = int(payload.get("page_number", 1))
        max_pages = int(payload.get("max_pages", 1))
        expect_more = page_number < max_pages
        return validate_search_tweets_pagination(
            page,
            expect_more=expect_more,
            current_cursor=payload.get("cursor"),
        )

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

    def _execute_task(self, task, *, auth: WebSessionAuth | None = None):
        if task.capability_id != CapabilityId.SEARCH_TWEETS:
            raise ValueError(f"Unsupported capability {task.capability_id.value}")

        recipe = self._recipe_for_task(task)
        payload = task.request_json["payload"]
        return acquire_search_tweets_page(
            recipe=recipe,
            auth=auth or self.auth,
            request=SearchTweetsRequest(
                query=str(payload["query"]),
                product=str(payload.get("product", "Top")),
                count=int(payload.get("page_size", 20)),
                cursor=payload.get("cursor"),
            ),
            transport=self.transport,
            raw_evidence_sink=self.raw_evidence_sink,
        )

    def _update_session_health_from_error(self, session_id: str, exc: ProtocolError) -> None:
        health = _session_health_for_protocol_error(exc)
        if health is None or self.session_store is None:
            return
        self.session_store.update_health(
            session_id,
            health=health,
            reason=f"{exc.error_class}:{exc.scope_hint}",
            cooldown_until=_session_cooldown_until(exc),
        )

    def _recipe_for_task(self, task):
        recipe_revision_id = task.plan_json["recipe_revision_id"]
        for binding in self.manifest.bindings:
            if binding.recipe.revision_id == recipe_revision_id:
                return binding.recipe
        raise ValueError(f"No recipe for {recipe_revision_id}")

    def _handle_failure(self, task, exc, *, envelope: RuntimeErrorEnvelope | None = None):
        envelope = envelope or classify_exception(exc)
        error_json = {
            "error_class": envelope.error_class,
            "message": envelope.message,
            "runtime_error": envelope.public_dict(),
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


def _duration_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))


def _session_health_for_protocol_error(exc: ProtocolError) -> SessionHealth | None:
    if exc.scope_hint != "SESSION":
        return None
    if exc.error_class == "AUTH_OR_SESSION_REJECTED":
        return SessionHealth.AUTH_EXPIRED
    if exc.error_class == "RATE_LIMITED":
        return SessionHealth.DEGRADED
    if "CHALLENGE" in exc.error_class:
        return SessionHealth.CHALLENGED
    if "LOCK" in exc.error_class:
        return SessionHealth.LOCKED
    return SessionHealth.DEGRADED


def _session_cooldown_until(exc: ProtocolError) -> str | None:
    if exc.scope_hint != "SESSION" or exc.error_class != "RATE_LIMITED":
        return None
    retry_after = exc.retry_after_seconds if exc.retry_after_seconds is not None else 300
    return (datetime.now(UTC) + timedelta(seconds=retry_after)).isoformat()
