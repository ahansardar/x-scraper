from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Mapping
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from xingestion.xprotocol.protocol import CapabilityId

from .ledger import CapabilityTask, OutboxEvent, RetentionResult, TaskState


class PostgresTaskLedger:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def create_task(
        self,
        *,
        idempotency_key: str,
        capability_id: CapabilityId,
        contract_version: int,
        request_json: Mapping[str, object],
        plan_json: Mapping[str, object],
    ) -> CapabilityTask:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty")

        now = _now()
        task_id = f"task-{uuid4().hex}"
        event_id = f"outbox-{uuid4().hex}"
        row: dict[str, object] | None = None
        conflict = False
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            try:
                with conn.transaction():
                    row = conn.execute(
                        """
                        INSERT INTO capability_tasks (
                            task_id,
                            idempotency_key,
                            capability_id,
                            contract_version,
                            state,
                            request_json,
                            plan_json,
                            result_json,
                            error_json,
                            attempt_count,
                            max_attempts,
                            next_attempt_at,
                            lease_owner,
                            lease_token,
                            lease_expires_at,
                            delivery_generation,
                            replay_origin_task_id,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, NULL, NULL, 0, 3,
                            NULL, NULL, NULL, NULL, 0, NULL, %s, %s
                        )
                        RETURNING *
                        """,
                        (
                            task_id,
                            idempotency_key,
                            capability_id.value,
                            contract_version,
                            TaskState.CREATED.value,
                            Jsonb(dict(request_json)),
                            Jsonb(dict(plan_json)),
                            now,
                            now,
                        ),
                    ).fetchone()
                    conn.execute(
                        """
                        INSERT INTO outbox_events (
                            event_id, task_id, event_type, payload_json, created_at, published_at
                        )
                        VALUES (%s, %s, %s, %s, %s, NULL)
                        """,
                        (
                            event_id,
                            task_id,
                            "CAPABILITY_TASK_CREATED",
                            Jsonb({"task_id": task_id}),
                            now,
                        ),
                    )
            except psycopg.errors.UniqueViolation:
                conflict = True

        if conflict:
            existing = self.get_task_by_idempotency_key(idempotency_key)
            if existing is None:
                raise RuntimeError(
                    f"idempotency conflict for {idempotency_key} could not be resolved"
                )
            return existing

        if row is None:
            raise RuntimeError("created task could not be reloaded")
        return _task_from_row(row)

    def replay_task(self, origin_task_id: str) -> CapabilityTask:
        origin = self.get_task(origin_task_id)
        if origin is None:
            raise ValueError(f"Task {origin_task_id} not found")
        if origin.state != TaskState.DEAD_LETTER:
            raise ValueError("Only DEAD_LETTER tasks can be replayed")

        now = _now()
        task_id = f"task-{uuid4().hex}"
        event_id = f"outbox-{uuid4().hex}"
        idempotency_key = f"replay:{origin.task_id}:{uuid4().hex}"
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            with conn.transaction():
                row = conn.execute(
                    """
                    INSERT INTO capability_tasks (
                        task_id,
                        idempotency_key,
                        capability_id,
                        contract_version,
                        state,
                        request_json,
                        plan_json,
                        result_json,
                        error_json,
                        attempt_count,
                        max_attempts,
                        next_attempt_at,
                        lease_owner,
                        lease_token,
                        lease_expires_at,
                        delivery_generation,
                        replay_origin_task_id,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, NULL, NULL, 0, %s,
                        NULL, NULL, NULL, NULL, 0, %s, %s, %s
                    )
                    RETURNING *
                    """,
                    (
                        task_id,
                        idempotency_key,
                        origin.capability_id.value,
                        origin.contract_version,
                        TaskState.CREATED.value,
                        Jsonb(dict(origin.request_json)),
                        Jsonb(dict(origin.plan_json)),
                        origin.max_attempts,
                        origin.task_id,
                        now,
                        now,
                    ),
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO outbox_events (
                        event_id, task_id, event_type, payload_json, created_at, published_at
                    )
                    VALUES (%s, %s, %s, %s, %s, NULL)
                    """,
                    (
                        event_id,
                        task_id,
                        "CAPABILITY_TASK_REPLAY_CREATED",
                        Jsonb({"task_id": task_id, "origin_task_id": origin.task_id}),
                        now,
                    ),
                )

        if row is None:
            raise RuntimeError("replay task could not be reloaded")
        return _task_from_row(row)

    def cancel_task(self, task_id: str, *, reason: str = "operator_cancelled") -> CapabilityTask:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if task.state not in {
            TaskState.CREATED,
            TaskState.ENQUEUED,
            TaskState.RETRY_SCHEDULED,
        }:
            raise ValueError(
                "Only CREATED, ENQUEUED, or RETRY_SCHEDULED tasks can be cancelled"
            )

        now = _now()
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            with conn.transaction():
                row = conn.execute(
                    """
                    UPDATE capability_tasks
                    SET state = %s,
                        error_json = %s,
                        next_attempt_at = NULL,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        updated_at = %s
                    WHERE task_id = %s
                      AND state IN (%s, %s, %s)
                    RETURNING *
                    """,
                    (
                        TaskState.CANCELLED.value,
                        Jsonb({"reason": reason}),
                        now,
                        task_id,
                        TaskState.CREATED.value,
                        TaskState.ENQUEUED.value,
                        TaskState.RETRY_SCHEDULED.value,
                    ),
                ).fetchone()
        if row is None:
            raise ValueError(f"Task {task_id} could not be cancelled")
        return _task_from_row(row)

    def apply_retention(self, *, days: int, dry_run: bool = True) -> RetentionResult:
        if days < 1:
            raise ValueError("retention days must be at least 1")

        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        terminal_states = (TaskState.DONE.value, TaskState.CANCELLED.value)
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM capability_tasks
                WHERE state IN (%s, %s)
                  AND updated_at < %s
                """,
                (*terminal_states, cutoff),
            ).fetchone()
            matched = int(row["count"])
            deleted = 0
            if not dry_run and matched:
                with conn.transaction():
                    conn.execute(
                        """
                        DELETE FROM outbox_events
                        WHERE task_id IN (
                            SELECT task_id
                            FROM capability_tasks
                            WHERE state IN (%s, %s)
                              AND updated_at < %s
                        )
                        """,
                        (*terminal_states, cutoff),
                    )
                    cursor = conn.execute(
                        """
                        DELETE FROM capability_tasks
                        WHERE state IN (%s, %s)
                          AND updated_at < %s
                        """,
                        (*terminal_states, cutoff),
                    )
                    deleted = cursor.rowcount

        return RetentionResult(
            cutoff=cutoff,
            matched_tasks=matched,
            deleted_tasks=deleted,
            dry_run=dry_run,
        )

    def task_state_counts(self) -> dict[str, int]:
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                """
                SELECT state, COUNT(*) AS count
                FROM capability_tasks
                GROUP BY state
                """
            ).fetchall()
        counts = {state.value: 0 for state in TaskState}
        counts.update({row["state"]: int(row["count"]) for row in rows})
        return counts

    def active_task_count(self, *, capability_id: CapabilityId | None = None) -> int:
        active_states = (
            TaskState.CREATED.value,
            TaskState.ENQUEUED.value,
            TaskState.RUNNING.value,
            TaskState.RETRY_SCHEDULED.value,
        )
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            if capability_id is None:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM capability_tasks
                    WHERE state IN (%s, %s, %s, %s)
                    """,
                    active_states,
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM capability_tasks
                    WHERE state IN (%s, %s, %s, %s)
                      AND capability_id = %s
                    """,
                    (*active_states, capability_id.value),
                ).fetchone()
        return int(row["count"])

    def outbox_stats(self) -> dict[str, int | str | None]:
        now_dt = datetime.now(UTC)
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                """
                SELECT COUNT(*) AS count, MIN(created_at) AS oldest_created_at
                FROM outbox_events
                WHERE published_at IS NULL
                """
            ).fetchone()

        oldest_dt = row["oldest_created_at"]
        oldest = _iso(oldest_dt)
        lag_seconds = None
        if oldest_dt is not None:
            lag_seconds = max(0, int((now_dt - oldest_dt.astimezone(UTC)).total_seconds()))
        return {
            "unpublished_events": int(row["count"]),
            "oldest_unpublished_at": oldest,
            "oldest_unpublished_lag_seconds": lag_seconds,
        }

    def list_unpublished_outbox_events(self, *, limit: int = 25) -> tuple[OutboxEvent, ...]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                """
                SELECT *
                FROM outbox_events
                WHERE published_at IS NULL
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return tuple(_outbox_event_from_row(row) for row in rows)

    def claim_next_outbox_event(self) -> OutboxEvent | None:
        now = _now()
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            with conn.transaction():
                candidate = conn.execute(
                    """
                    SELECT *
                    FROM outbox_events
                    WHERE published_at IS NULL
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                ).fetchone()
                if candidate is None:
                    return None
                row = conn.execute(
                    """
                    UPDATE outbox_events
                    SET published_at = %s
                    WHERE event_id = %s AND published_at IS NULL
                    RETURNING *
                    """,
                    (now, candidate["event_id"]),
                ).fetchone()

        if row is None:
            raise RuntimeError("claimed outbox event could not be reloaded")
        return _outbox_event_from_row(row)

    def create_outbox_event(
        self,
        *,
        task_id: str,
        event_type: str = "CAPABILITY_TASK_RETRY_DUE",
        payload_json: Mapping[str, object] | None = None,
    ) -> OutboxEvent:
        now = _now()
        event_id = f"outbox-{uuid4().hex}"
        payload_json = payload_json or {"task_id": task_id}
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                """
                INSERT INTO outbox_events (
                    event_id, task_id, event_type, payload_json, created_at, published_at
                )
                VALUES (%s, %s, %s, %s, %s, NULL)
                RETURNING *
                """,
                (event_id, task_id, event_type, Jsonb(dict(payload_json)), now),
            ).fetchone()

        if row is None:
            raise RuntimeError("created outbox event could not be reloaded")
        return _outbox_event_from_row(row)

    def due_retry_tasks(self, *, now: str | None = None) -> tuple[CapabilityTask, ...]:
        now = now or _now()
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                """
                SELECT *
                FROM capability_tasks
                WHERE state = %s
                  AND next_attempt_at IS NOT NULL
                  AND next_attempt_at <= %s
                ORDER BY next_attempt_at ASC
                """,
                (TaskState.RETRY_SCHEDULED.value, now),
            ).fetchall()
        return tuple(_task_from_row(row) for row in rows)

    def enqueue_due_retries(self, *, now: str | None = None) -> int:
        count = 0
        for task in self.due_retry_tasks(now=now):
            self.transition_task(
                task.task_id,
                from_state=TaskState.RETRY_SCHEDULED,
                to_state=TaskState.ENQUEUED,
            )
            self.create_outbox_event(task_id=task.task_id)
            count += 1
        return count

    def recover_expired_leases(self, *, now: str | None = None) -> int:
        now = now or _now()
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                """
                SELECT *
                FROM capability_tasks
                WHERE state = %s
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= %s
                ORDER BY lease_expires_at ASC
                """,
                (TaskState.RUNNING.value, now),
            ).fetchall()

        count = 0
        for row in rows:
            task = _task_from_row(row)
            self.reclaim_expired_lease(task.task_id, now=now)
            self.create_outbox_event(
                task_id=task.task_id,
                event_type="CAPABILITY_TASK_LEASE_EXPIRED",
            )
            count += 1
        return count

    def reclaim_expired_lease(self, task_id: str, *, now: str | None = None) -> CapabilityTask:
        now = now or _now()
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                """
                UPDATE capability_tasks
                SET state = %s,
                    lease_owner = NULL,
                    lease_token = NULL,
                    lease_expires_at = NULL,
                    updated_at = %s
                WHERE task_id = %s
                  AND state = %s
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= %s
                RETURNING *
                """,
                (TaskState.ENQUEUED.value, now, task_id, TaskState.RUNNING.value, now),
            ).fetchone()
        if row is None:
            raise ValueError(f"Task {task_id} does not have an expired lease")
        return _task_from_row(row)

    def acquire_execution_lease(
        self,
        task_id: str,
        *,
        owner: str,
        lease_expires_at: str,
    ) -> CapabilityTask:
        now = _now()
        token = f"lease-{uuid4().hex}"
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                """
                UPDATE capability_tasks
                SET state = %s,
                    lease_owner = %s,
                    lease_token = %s,
                    lease_expires_at = %s,
                    delivery_generation = delivery_generation + 1,
                    attempt_count = attempt_count + 1,
                    updated_at = %s
                WHERE task_id = %s
                  AND state = %s
                  AND lease_token IS NULL
                RETURNING *
                """,
                (
                    TaskState.RUNNING.value,
                    owner,
                    token,
                    lease_expires_at,
                    now,
                    task_id,
                    TaskState.ENQUEUED.value,
                ),
            ).fetchone()
        if row is None:
            raise ValueError(f"Task {task_id} could not acquire execution lease")
        return _task_from_row(row)

    def renew_execution_lease(
        self,
        task_id: str,
        *,
        lease_token: str,
        delivery_generation: int,
        lease_expires_at: str,
    ) -> CapabilityTask:
        now = _now()
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                """
                UPDATE capability_tasks
                SET lease_expires_at = %s,
                    updated_at = %s
                WHERE task_id = %s
                  AND state = %s
                  AND lease_token = %s
                  AND delivery_generation = %s
                RETURNING *
                """,
                (
                    lease_expires_at,
                    now,
                    task_id,
                    TaskState.RUNNING.value,
                    lease_token,
                    delivery_generation,
                ),
            ).fetchone()
        if row is None:
            raise ValueError(f"Task {task_id} could not renew execution lease")
        return _task_from_row(row)

    def get_outbox_event(self, event_id: str) -> OutboxEvent | None:
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM outbox_events WHERE event_id = %s",
                (event_id,),
            ).fetchone()
        return _outbox_event_from_row(row) if row else None

    def list_outbox_events_for_task(self, task_id: str) -> tuple[OutboxEvent, ...]:
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                """
                SELECT *
                FROM outbox_events
                WHERE task_id = %s
                ORDER BY created_at ASC
                """,
                (task_id,),
            ).fetchall()
        return tuple(_outbox_event_from_row(row) for row in rows)

    def get_task(self, task_id: str) -> CapabilityTask | None:
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM capability_tasks WHERE task_id = %s",
                (task_id,),
            ).fetchone()
        return _task_from_row(row) if row else None

    def get_task_by_idempotency_key(self, idempotency_key: str) -> CapabilityTask | None:
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM capability_tasks WHERE idempotency_key = %s",
                (idempotency_key,),
            ).fetchone()
        return _task_from_row(row) if row else None

    def list_recent_tasks(self, *, limit: int = 25) -> tuple[CapabilityTask, ...]:
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                """
                SELECT *
                FROM capability_tasks
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return tuple(_task_from_row(row) for row in rows)

    def list_recent_task_errors(self, *, limit: int = 25) -> tuple[CapabilityTask, ...]:
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                """
                SELECT *
                FROM capability_tasks
                WHERE error_json IS NOT NULL
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return tuple(_task_from_row(row) for row in rows)

    def list_done_task_ids_for_release(
        self, *, release_id: str, limit: int
    ) -> tuple[str, ...]:
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                """
                SELECT task_id
                FROM capability_tasks
                WHERE state = %s
                  AND plan_json ->> 'release_id' = %s
                  AND result_json IS NOT NULL
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (TaskState.DONE.value, release_id, limit),
            ).fetchall()
        return tuple(row["task_id"] for row in rows)

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
        now = _now()
        lease_clause = ""
        params_extra: list[object] = []
        if lease_token is not None:
            lease_clause += " AND lease_token = %s"
            params_extra.append(lease_token)
        if delivery_generation is not None:
            lease_clause += " AND delivery_generation = %s"
            params_extra.append(delivery_generation)

        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                f"""
                UPDATE capability_tasks
                SET state = %s,
                    result_json = COALESCE(%s, result_json),
                    error_json = COALESCE(%s, error_json),
                    next_attempt_at = %s,
                    attempt_count = attempt_count + %s,
                    lease_owner = CASE WHEN %s THEN NULL ELSE lease_owner END,
                    lease_token = CASE WHEN %s THEN NULL ELSE lease_token END,
                    lease_expires_at = CASE WHEN %s THEN NULL ELSE lease_expires_at END,
                    updated_at = %s
                WHERE task_id = %s AND state = %s{lease_clause}
                RETURNING *
                """,
                (
                    to_state.value,
                    Jsonb(dict(result_json)) if result_json is not None else None,
                    Jsonb(dict(error_json)) if error_json is not None else None,
                    next_attempt_at,
                    1 if increment_attempt else 0,
                    bool(clear_lease),
                    bool(clear_lease),
                    bool(clear_lease),
                    now,
                    task_id,
                    from_state.value,
                    *params_extra,
                ),
            ).fetchone()

        if row is None:
            raise ValueError(f"Task {task_id} is not in expected state {from_state.value}")
        return _task_from_row(row)


def _task_from_row(row: Mapping[str, object]) -> CapabilityTask:
    return CapabilityTask(
        task_id=row["task_id"],
        idempotency_key=row["idempotency_key"],
        capability_id=CapabilityId(row["capability_id"]),
        contract_version=int(row["contract_version"]),
        state=TaskState(row["state"]),
        request_json=row["request_json"],
        plan_json=row["plan_json"],
        result_json=row["result_json"],
        error_json=row["error_json"],
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        next_attempt_at=_iso(row["next_attempt_at"]),
        lease_owner=row["lease_owner"],
        lease_token=row["lease_token"],
        lease_expires_at=_iso(row["lease_expires_at"]),
        delivery_generation=int(row["delivery_generation"]),
        replay_origin_task_id=row["replay_origin_task_id"],
        created_at=_iso(row["created_at"]),
        updated_at=_iso(row["updated_at"]),
    )


def _outbox_event_from_row(row: Mapping[str, object]) -> OutboxEvent:
    return OutboxEvent(
        event_id=row["event_id"],
        task_id=row["task_id"],
        event_type=row["event_type"],
        payload_json=row["payload_json"],
        created_at=_iso(row["created_at"]),
        published_at=_iso(row["published_at"]),
    )


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


def _now() -> str:
    return datetime.now(UTC).isoformat()
