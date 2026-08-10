from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Mapping, Protocol
from uuid import uuid4

from xrev.protocol import CapabilityId


class TaskState(StrEnum):
    CREATED = "CREATED"
    ENQUEUED = "ENQUEUED"
    RUNNING = "RUNNING"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    DONE = "DONE"
    DEAD_LETTER = "DEAD_LETTER"


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

    def claim_next_outbox_event(self) -> OutboxEvent | None:
        """Claim the oldest unpublished outbox event."""

    def get_task(self, task_id: str) -> CapabilityTask | None:
        """Load a task by ID."""

    def transition_task(
        self,
        task_id: str,
        *,
        from_state: TaskState,
        to_state: TaskState,
    ) -> CapabilityTask:
        """Transition task state only when the expected source state matches."""


class SQLiteTaskLedger:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._initialize()

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
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            try:
                conn.execute(
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
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                    """,
                    (
                        task_id,
                        idempotency_key,
                        capability_id.value,
                        contract_version,
                        TaskState.CREATED.value,
                        _json(request_json),
                        _json(plan_json),
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO outbox_events (
                        event_id,
                        task_id,
                        event_type,
                        payload_json,
                        created_at,
                        published_at
                    )
                    VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        event_id,
                        task_id,
                        "CAPABILITY_TASK_CREATED",
                        _json({"task_id": task_id}),
                        now,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                existing = self.get_task_by_idempotency_key(idempotency_key)
                if existing is None:
                    raise
                return existing

        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError("created task could not be reloaded")
        return task

    def claim_next_outbox_event(self) -> OutboxEvent | None:
        now = _now()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT *
                FROM outbox_events
                WHERE published_at IS NULL
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.commit()
                return None

            conn.execute(
                """
                UPDATE outbox_events
                SET published_at = ?
                WHERE event_id = ? AND published_at IS NULL
                """,
                (now, row["event_id"]),
            )
            conn.commit()

        event = self.get_outbox_event(row["event_id"])
        if event is None:
            raise RuntimeError("claimed outbox event could not be reloaded")
        return event

    def get_outbox_event(self, event_id: str) -> OutboxEvent | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM outbox_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return _outbox_event_from_row(row) if row else None

    def list_outbox_events_for_task(self, task_id: str) -> tuple[OutboxEvent, ...]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM outbox_events
                WHERE task_id = ?
                ORDER BY created_at ASC
                """,
                (task_id,),
            ).fetchall()
        return tuple(_outbox_event_from_row(row) for row in rows)

    def get_task(self, task_id: str) -> CapabilityTask | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM capability_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return _task_from_row(row) if row else None

    def get_task_by_idempotency_key(self, idempotency_key: str) -> CapabilityTask | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM capability_tasks WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return _task_from_row(row) if row else None

    def transition_task(
        self,
        task_id: str,
        *,
        from_state: TaskState,
        to_state: TaskState,
        result_json: Mapping[str, object] | None = None,
        error_json: Mapping[str, object] | None = None,
    ) -> CapabilityTask:
        now = _now()
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                UPDATE capability_tasks
                SET state = ?,
                    result_json = COALESCE(?, result_json),
                    error_json = COALESCE(?, error_json),
                    updated_at = ?
                WHERE task_id = ? AND state = ?
                """,
                (
                    to_state.value,
                    _json(result_json) if result_json is not None else None,
                    _json(error_json) if error_json is not None else None,
                    now,
                    task_id,
                    from_state.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    f"Task {task_id} is not in expected state {from_state.value}"
                )
            conn.commit()

        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError("transitioned task could not be reloaded")
        return task

    def _initialize(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_tasks (
                    task_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    capability_id TEXT NOT NULL,
                    contract_version INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            _ensure_column(conn, "capability_tasks", "result_json", "TEXT")
            _ensure_column(conn, "capability_tasks", "error_json", "TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbox_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    published_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES capability_tasks(task_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_outbox_unpublished
                ON outbox_events (published_at, created_at)
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _task_from_row(row: sqlite3.Row) -> CapabilityTask:
    return CapabilityTask(
        task_id=row["task_id"],
        idempotency_key=row["idempotency_key"],
        capability_id=CapabilityId(row["capability_id"]),
        contract_version=int(row["contract_version"]),
        state=TaskState(row["state"]),
        request_json=json.loads(row["request_json"]),
        plan_json=json.loads(row["plan_json"]),
        result_json=json.loads(row["result_json"]) if row["result_json"] else None,
        error_json=json.loads(row["error_json"]) if row["error_json"] else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _outbox_event_from_row(row: sqlite3.Row) -> OutboxEvent:
    return OutboxEvent(
        event_id=row["event_id"],
        task_id=row["task_id"],
        event_type=row["event_type"],
        payload_json=json.loads(row["payload_json"]),
        created_at=row["created_at"],
        published_at=row["published_at"],
    )


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
