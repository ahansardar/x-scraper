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
    created_at: str
    updated_at: str


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
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    ) -> CapabilityTask:
        now = _now()
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                UPDATE capability_tasks
                SET state = ?, updated_at = ?
                WHERE task_id = ? AND state = ?
                """,
                (to_state.value, now, task_id, from_state.value),
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
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(UTC).isoformat()
