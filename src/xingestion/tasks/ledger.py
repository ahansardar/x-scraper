from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Protocol

from xingestion.xprotocol.protocol import CapabilityId


class TaskState(StrEnum):
    CREATED = "CREATED"
    ENQUEUED = "ENQUEUED"
    RUNNING = "RUNNING"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    DONE = "DONE"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class CapabilityTask:
    task_id: str
    idempotency_key: str
    capability_id: CapabilityId
    contract_version: int
    state: TaskState
    request_json: Mapping[str, object]
    plan_json: Mapping[str, object]
    result_json: Mapping[str, object] | None
    error_json: Mapping[str, object] | None
    attempt_count: int
    max_attempts: int
    next_attempt_at: str | None
    lease_owner: str | None
    lease_token: str | None
    lease_expires_at: str | None
    delivery_generation: int
    replay_origin_task_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class OutboxEvent:
    event_id: str
    task_id: str
    event_type: str
    payload_json: Mapping[str, object]
    created_at: str
    published_at: str | None


@dataclass(frozen=True)
class RetentionResult:
    cutoff: str
    matched_tasks: int
    deleted_tasks: int
    dry_run: bool


class TaskLedger(Protocol):
    def create_task(
        self,
        *,
        idempotency_key: str,
        capability_id: CapabilityId,
        contract_version: int,
        request_json: Mapping[str, object],
        plan_json: Mapping[str, object],
    ) -> CapabilityTask:
        """Create a durable task or return the existing idempotent task."""

    def replay_task(self, origin_task_id: str) -> CapabilityTask:
        """Create a new task linked to a DEAD_LETTER origin task."""

    def cancel_task(self, task_id: str, *, reason: str = "operator_cancelled") -> CapabilityTask:
        """Cancel a task that has not yet started running."""

    def apply_retention(self, *, days: int, dry_run: bool = True) -> RetentionResult:
        """Delete terminal tasks/outbox events older than the retention window."""

    def task_state_counts(self) -> dict[str, int]:
        """Count tasks grouped by state."""

    def active_task_count(self, *, capability_id: CapabilityId | None = None) -> int:
        """Count tasks in an active (non-terminal) state."""

    def outbox_stats(self) -> dict[str, int | str | None]:
        """Report unpublished outbox event count and oldest lag."""

    def list_unpublished_outbox_events(self, *, limit: int = 25) -> tuple[OutboxEvent, ...]:
        """List unpublished outbox events, oldest first."""

    def claim_next_outbox_event(self) -> OutboxEvent | None:
        """Claim the oldest unpublished outbox event."""

    def create_outbox_event(
        self,
        *,
        task_id: str,
        event_type: str = "CAPABILITY_TASK_RETRY_DUE",
        payload_json: Mapping[str, object] | None = None,
    ) -> OutboxEvent:
        """Create a new outbox event for a task."""

    def due_retry_tasks(self, *, now: str | None = None) -> tuple[CapabilityTask, ...]:
        """List RETRY_SCHEDULED tasks whose next_attempt_at has passed."""

    def enqueue_due_retries(self, *, now: str | None = None) -> int:
        """Move due RETRY_SCHEDULED tasks back to ENQUEUED."""

    def recover_expired_leases(self, *, now: str | None = None) -> int:
        """Reclaim RUNNING tasks whose lease has expired."""

    def reclaim_expired_lease(self, task_id: str, *, now: str | None = None) -> CapabilityTask:
        """Reclaim a single expired lease back to ENQUEUED."""

    def acquire_execution_lease(
        self,
        task_id: str,
        *,
        owner: str,
        lease_expires_at: str,
    ) -> CapabilityTask:
        """Acquire an execution lease, fencing on ENQUEUED state."""

    def renew_execution_lease(
        self,
        task_id: str,
        *,
        lease_token: str,
        delivery_generation: int,
        lease_expires_at: str,
    ) -> CapabilityTask:
        """Renew an execution lease, fencing on lease token and delivery generation."""

    def get_outbox_event(self, event_id: str) -> OutboxEvent | None:
        """Load an outbox event by ID."""

    def list_outbox_events_for_task(self, task_id: str) -> tuple[OutboxEvent, ...]:
        """List outbox events for a task."""

    def get_task(self, task_id: str) -> CapabilityTask | None:
        """Load a task by ID."""

    def get_task_by_idempotency_key(self, idempotency_key: str) -> CapabilityTask | None:
        """Load a task by idempotency key."""

    def list_recent_tasks(self, *, limit: int = 25) -> tuple[CapabilityTask, ...]:
        """List the most recently created tasks."""

    def list_recent_task_errors(self, *, limit: int = 25) -> tuple[CapabilityTask, ...]:
        """List the most recently updated tasks that carry an error."""

    def list_done_task_ids_for_release(
        self, *, release_id: str, limit: int
    ) -> tuple[str, ...]:
        """List DONE task IDs bound to a release, most recently updated first."""

    def transition_task(
        self,
        task_id: str,
        *,
        from_state: TaskState,
        to_state: TaskState,
        result_json: Mapping[str, object] | None = None,
        error_json: Mapping[str, object] | None = None,
        next_attempt_at: str | None = None,
        increment_attempt: bool = False,
        lease_token: str | None = None,
        delivery_generation: int | None = None,
        clear_lease: bool = False,
    ) -> CapabilityTask:
        """Transition task state only when the expected source state (and fencing) matches."""
