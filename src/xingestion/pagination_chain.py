from __future__ import annotations

from dataclasses import dataclass

from xingestion.tasks import CapabilityTask, TaskLedger

PAGINATION_ERROR_CLASSES = frozenset(
    {
        "PAGINATION_CURSOR_MISSING",
        "PAGINATION_EMPTY_CONTINUATION",
        "PAGINATION_CURSOR_LOOP",
    }
)


def is_pagination_error_class(error_class: str | None) -> bool:
    return error_class in PAGINATION_ERROR_CLASSES


@dataclass(frozen=True)
class PaginationChainEntry:
    task_id: str
    page_number: int
    cursor: str | None
    state: str

    def public_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "page_number": self.page_number,
            "cursor": self.cursor,
            "state": self.state,
        }


def walk_pagination_chain(
    ledger: TaskLedger, task: CapabilityTask
) -> tuple[PaginationChainEntry, ...]:
    """Ancestors of `task` in its pagination continuation chain, oldest first.

    Continuation tasks link back via `request_json.payload.
    pagination_parent_task_id` (set in LocalWorker._queue_continuation_if_needed).
    Walks that chain backward through the ledger; does not include `task`
    itself. A task with no continuation lineage returns an empty tuple.
    Stops on a missing or cyclic parent reference rather than raising --
    this is diagnostic evidence, not a correctness-critical path.
    """
    entries: list[PaginationChainEntry] = []
    payload = (task.request_json or {}).get("payload", {})
    parent_task_id = payload.get("pagination_parent_task_id")
    visited = {task.task_id}
    while parent_task_id and parent_task_id not in visited:
        visited.add(parent_task_id)
        parent = ledger.get_task(parent_task_id)
        if parent is None:
            break
        parent_payload = (parent.request_json or {}).get("payload", {})
        entries.append(
            PaginationChainEntry(
                task_id=parent.task_id,
                page_number=int(parent_payload.get("page_number") or 0),
                cursor=parent_payload.get("cursor"),
                state=parent.state.value,
            )
        )
        parent_task_id = parent_payload.get("pagination_parent_task_id")
    entries.reverse()
    return tuple(entries)
