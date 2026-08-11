from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3

from xingestion.errors import RuntimeErrorEnvelope, envelope_from_task_error
from xingestion.tasks import TaskState


DEFAULT_ACTION_STATES = (TaskState.DEAD_LETTER, TaskState.RETRY_SCHEDULED)


@dataclass(frozen=True)
class OperatorTaskAction:
    task_id: str
    state: str
    capability_id: str
    attempt_count: int
    max_attempts: int
    next_attempt_at: str | None
    updated_at: str
    error_class: str | None
    severity: str
    scope: str
    operator_action: str
    retryable: bool
    replayable: bool
    cancellable: bool
    exportable: bool

    def public_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "capability_id": self.capability_id,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "next_attempt_at": self.next_attempt_at,
            "updated_at": self.updated_at,
            "error_class": self.error_class,
            "severity": self.severity,
            "scope": self.scope,
            "operator_action": self.operator_action,
            "retryable": self.retryable,
            "replayable": self.replayable,
            "cancellable": self.cancellable,
            "exportable": self.exportable,
        }


def list_operator_task_actions(
    db_path: str | Path,
    *,
    states: tuple[TaskState, ...] = DEFAULT_ACTION_STATES,
    limit: int = 25,
) -> tuple[OperatorTaskAction, ...]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if not states:
        raise ValueError("at least one state is required")

    state_values = tuple(state.value for state in states)
    placeholders = ",".join("?" for _ in state_values)
    query = f"""
        SELECT *
        FROM capability_tasks
        WHERE state IN ({placeholders})
        ORDER BY updated_at DESC
        LIMIT ?
    """
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, (*state_values, limit)).fetchall()
    return tuple(_action_from_row(row) for row in rows)


def _action_from_row(row: sqlite3.Row) -> OperatorTaskAction:
    envelope = _runtime_error(row)
    state = str(row["state"])
    return OperatorTaskAction(
        task_id=row["task_id"],
        state=state,
        capability_id=row["capability_id"],
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        next_attempt_at=row["next_attempt_at"],
        updated_at=row["updated_at"],
        error_class=envelope.error_class if envelope else None,
        severity=envelope.severity.value if envelope else "UNKNOWN",
        scope=envelope.scope.value if envelope else "UNKNOWN",
        operator_action=_operator_action(state, envelope),
        retryable=envelope.retryable if envelope else state == TaskState.RETRY_SCHEDULED.value,
        replayable=state == TaskState.DEAD_LETTER.value,
        cancellable=state in {
            TaskState.CREATED.value,
            TaskState.ENQUEUED.value,
            TaskState.RETRY_SCHEDULED.value,
        },
        exportable=bool(row["error_json"]),
    )


def _runtime_error(row: sqlite3.Row) -> RuntimeErrorEnvelope | None:
    if not row["error_json"]:
        return None
    try:
        error_json = json.loads(row["error_json"])
    except json.JSONDecodeError:
        error_json = {
            "error_class": "INVALID_ERROR_JSON",
            "message": "Task error_json could not be decoded",
        }
    return envelope_from_task_error(error_json)


def _operator_action(state: str, envelope: RuntimeErrorEnvelope | None) -> str:
    if envelope is not None:
        if state == TaskState.DEAD_LETTER.value:
            return f"{envelope.operator_action}; export_or_replay_after_review"
        if state == TaskState.RETRY_SCHEDULED.value:
            return f"{envelope.operator_action}; wait_for_retry_or_cancel"
        return envelope.operator_action
    if state == TaskState.RETRY_SCHEDULED.value:
        return "wait_for_retry_or_cancel"
    if state == TaskState.DEAD_LETTER.value:
        return "export_failed_task_and_replay_after_review"
    return "inspect_task"
