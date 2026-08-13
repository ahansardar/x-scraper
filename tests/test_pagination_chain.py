import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.pagination_chain import (
    PAGINATION_ERROR_CLASSES,
    is_pagination_error_class,
    walk_pagination_chain,
)
from xingestion.tasks import CapabilityTask, TaskState
from xingestion.xprotocol.protocol import CapabilityId


class FakeLedger:
    def __init__(self, tasks):
        self._tasks = {task.task_id: task for task in tasks}

    def get_task(self, task_id):
        return self._tasks.get(task_id)


def _task(
    task_id,
    *,
    page_number,
    cursor,
    parent_task_id=None,
    root_task_id=None,
    state=TaskState.DONE,
):
    payload = {
        "query": "india",
        "page_number": page_number,
        "cursor": cursor,
        "max_pages": 5,
    }
    if parent_task_id:
        payload["pagination_parent_task_id"] = parent_task_id
    if root_task_id:
        payload["pagination_root_task_id"] = root_task_id
    return CapabilityTask(
        task_id=task_id,
        idempotency_key=f"key-{task_id}",
        capability_id=CapabilityId.SEARCH_TWEETS,
        contract_version=1,
        state=state,
        request_json={"payload": payload},
        plan_json={},
        result_json=None,
        error_json=None,
        attempt_count=1,
        max_attempts=5,
        next_attempt_at=None,
        lease_owner=None,
        lease_token=None,
        lease_expires_at=None,
        delivery_generation=1,
        replay_origin_task_id=None,
        created_at="2026-08-13T00:00:00+00:00",
        updated_at="2026-08-13T00:00:00+00:00",
    )


class PaginationChainTests(unittest.TestCase):
    def test_walk_returns_empty_for_a_root_task_with_no_parent(self):
        root = _task("task-1", page_number=1, cursor=None)
        ledger = FakeLedger([root])

        chain = walk_pagination_chain(ledger, root)

        self.assertEqual(chain, ())

    def test_walk_returns_ancestors_oldest_first(self):
        root = _task("task-1", page_number=1, cursor=None)
        page2 = _task(
            "task-2",
            page_number=2,
            cursor="cursor-a",
            parent_task_id="task-1",
            root_task_id="task-1",
        )
        page3 = _task(
            "task-3",
            page_number=3,
            cursor="cursor-b",
            parent_task_id="task-2",
            root_task_id="task-1",
        )
        ledger = FakeLedger([root, page2, page3])

        chain = walk_pagination_chain(ledger, page3)

        self.assertEqual([entry.task_id for entry in chain], ["task-1", "task-2"])
        self.assertEqual([entry.cursor for entry in chain], [None, "cursor-a"])
        self.assertEqual([entry.page_number for entry in chain], [1, 2])

    def test_walk_stops_on_missing_parent_reference(self):
        page2 = _task(
            "task-2", page_number=2, cursor="cursor-a", parent_task_id="task-missing"
        )
        ledger = FakeLedger([page2])

        chain = walk_pagination_chain(ledger, page2)

        self.assertEqual(chain, ())

    def test_walk_stops_on_cyclic_parent_reference(self):
        # Defensive: a corrupted chain shouldn't infinite-loop.
        a = _task("task-a", page_number=1, cursor=None, parent_task_id="task-b")
        b = _task("task-b", page_number=2, cursor="cursor-a", parent_task_id="task-a")
        ledger = FakeLedger([a, b])

        chain = walk_pagination_chain(ledger, a)

        self.assertEqual([entry.task_id for entry in chain], ["task-b"])

    def test_is_pagination_error_class(self):
        for error_class in PAGINATION_ERROR_CLASSES:
            self.assertTrue(is_pagination_error_class(error_class))
        self.assertFalse(is_pagination_error_class("OPERATION_NOT_FOUND"))
        self.assertFalse(is_pagination_error_class(None))


if __name__ == "__main__":
    unittest.main()
