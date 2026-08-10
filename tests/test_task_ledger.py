import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.capabilities import (
    CapabilityPlanner,
    CapabilityRequest,
    SearchTweetsInput,
)
from xingestion.tasks import SQLiteTaskLedger, TaskState
from xrev.protocol import CapabilityId, ProtocolReleaseManifest


def load_manifest():
    return ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )


def make_request_and_plan():
    request = CapabilityRequest(
        capability_id=CapabilityId.SEARCH_TWEETS,
        contract_version=1,
        payload=SearchTweetsInput(query="india", page_size=20),
    )
    plan = CapabilityPlanner(load_manifest()).plan(request)
    return request, plan


class TaskLedgerTests(unittest.TestCase):
    def test_creates_and_reloads_durable_task(self):
        request, plan = make_request_and_plan()
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="search-india-1",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )

            reloaded = ledger.get_task(task.task_id)

            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.state, TaskState.CREATED)
            self.assertEqual(reloaded.capability_id, CapabilityId.SEARCH_TWEETS)
            self.assertEqual(reloaded.request_json["capability_id"], "SEARCH_TWEETS")
            self.assertEqual(reloaded.plan_json["release_id"], plan.release_id)

    def test_idempotency_key_returns_existing_task(self):
        request, plan = make_request_and_plan()
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            first = ledger.create_task(
                idempotency_key="same-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            second = ledger.create_task(
                idempotency_key="same-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )

            self.assertEqual(first.task_id, second.task_id)
            self.assertEqual(second.state, TaskState.CREATED)

    def test_state_transition_requires_expected_current_state(self):
        request, plan = make_request_and_plan()
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="transition-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )

            enqueued = ledger.transition_task(
                task.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.ENQUEUED,
            )

            self.assertEqual(enqueued.state, TaskState.ENQUEUED)
            with self.assertRaisesRegex(ValueError, "expected state"):
                ledger.transition_task(
                    task.task_id,
                    from_state=TaskState.CREATED,
                    to_state=TaskState.RUNNING,
                )


if __name__ == "__main__":
    unittest.main()
