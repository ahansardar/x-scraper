import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))

from xingestion.capabilities import CapabilityPlanner, CapabilityRequest, SearchTweetsInput
from xingestion.outbox_operations import list_outbox_queue, process_outbox
from xingestion.tasks import SQLiteTaskLedger, TaskState
from xingestion.workers import WorkerResult
from xingestion.xprotocol.protocol import CapabilityId, ProtocolReleaseManifest


def make_task(ledger):
    manifest = ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )
    request = CapabilityRequest(
        capability_id=CapabilityId.SEARCH_TWEETS,
        contract_version=1,
        payload=SearchTweetsInput(query="india", page_size=20),
    )
    plan = CapabilityPlanner(manifest).plan(request)
    return ledger.create_task(
        idempotency_key="outbox-ops-key",
        capability_id=request.capability_id,
        contract_version=request.contract_version,
        request_json=request.public_dict(),
        plan_json=plan.public_dict(),
    )


class StubWorker:
    def __init__(self, ledger, task_id):
        self.ledger = ledger
        self.task_id = task_id
        self.calls = 0

    def process_one(self):
        self.calls += 1
        event = self.ledger.claim_next_outbox_event()
        if event is None:
            return WorkerResult(processed=False)
        task = self.ledger.transition_task(
            self.task_id,
            from_state=TaskState.CREATED,
            to_state=TaskState.ENQUEUED,
        )
        return WorkerResult(
            processed=True,
            task_id=task.task_id,
            state=task.state,
            message="stub processed",
        )


class OutboxOperationsTests(unittest.TestCase):
    def test_list_outbox_queue_includes_task_state_and_age(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = make_task(ledger)

            payload = list_outbox_queue(
                ledger,
                limit=10,
                now="2999-01-01T00:00:00+00:00",
            )

            self.assertEqual(payload["stats"]["unpublished_events"], 1)
            self.assertEqual(payload["events"][0]["task_id"], task.task_id)
            self.assertEqual(payload["events"][0]["task_state"], "CREATED")
            self.assertIsInstance(payload["events"][0]["age_seconds"], int)

    def test_process_outbox_uses_worker_until_limit_or_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = make_task(ledger)
            worker = StubWorker(ledger, task.task_id)

            result = process_outbox(ledger=ledger, worker=worker, limit=5)

            self.assertEqual(result.processed_events, 1)
            self.assertEqual(result.before["unpublished_events"], 1)
            self.assertEqual(result.after["unpublished_events"], 0)
            self.assertEqual(result.worker_results[0].task_id, task.task_id)
            self.assertEqual(worker.calls, 2)


if __name__ == "__main__":
    unittest.main()
