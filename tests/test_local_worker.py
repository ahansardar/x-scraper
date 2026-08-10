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
from xingestion.workers import LocalWorker
from xrev.evidence import FileRawEvidenceSink
from xrev.protocol import CapabilityId, ProtocolReleaseManifest
from xrev.runtime import ProtocolHttpResponse, WebSessionAuth


class FakeTransport:
    def send(self, request):
        return ProtocolHttpResponse(
            200,
            {
                "entries": [
                    {
                        "tweet_results": {
                            "result": {
                                "__typename": "Tweet",
                                "rest_id": "1",
                                "core": {
                                    "user_results": {
                                        "result": {
                                            "core": {
                                                "screen_name": "alice",
                                                "name": "Alice",
                                            }
                                        }
                                    }
                                },
                                "legacy": {
                                    "id_str": "1",
                                    "full_text": "hello",
                                    "created_at": "Mon Aug 10 12:00:00 +0000 2026",
                                    "favorite_count": 7,
                                    "retweet_count": 3,
                                    "reply_count": 2,
                                    "quote_count": 1,
                                    "bookmark_count": 4,
                                },
                                "views": {"count": "50"},
                            }
                        }
                    }
                ]
            },
        )


class FlakyTransport:
    def __init__(self):
        self.calls = 0

    def send(self, request):
        self.calls += 1
        if self.calls == 1:
            return ProtocolHttpResponse(500, {"errors": ["temporary"]})
        return FakeTransport().send(request)


def load_manifest():
    return ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )


class LocalWorkerTests(unittest.TestCase):
    def test_worker_claims_outbox_and_completes_task(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="worker-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            worker = LocalWorker(
                ledger=ledger,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
                transport=FakeTransport(),
                raw_evidence_sink=FileRawEvidenceSink(Path(temp_dir) / "raw"),
            )

            result = worker.process_one()
            reloaded = ledger.get_task(task.task_id)

            self.assertTrue(result.processed)
            self.assertEqual(result.state, TaskState.DONE)
            self.assertIsNotNone(result.raw_evidence_ref)
            self.assertEqual(reloaded.state, TaskState.DONE)
            self.assertEqual(
                reloaded.result_json["raw_evidence"]["evidence_id"],
                result.raw_evidence_ref.evidence_id,
            )
            self.assertIsNone(worker.process_one().task_id)

    def test_worker_schedules_retry_for_retryable_protocol_error(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="retry-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            transport = FlakyTransport()
            worker = LocalWorker(
                ledger=ledger,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
                transport=transport,
                raw_evidence_sink=FileRawEvidenceSink(Path(temp_dir) / "raw"),
            )

            first = worker.process_one()
            scheduled = ledger.get_task(task.task_id)

            self.assertEqual(first.state, TaskState.RETRY_SCHEDULED)
            self.assertEqual(scheduled.state, TaskState.RETRY_SCHEDULED)
            self.assertEqual(scheduled.attempt_count, 1)
            self.assertIsNotNone(scheduled.next_attempt_at)
            self.assertEqual(transport.calls, 1)

            ledger.transition_task(
                task.task_id,
                from_state=TaskState.RETRY_SCHEDULED,
                to_state=TaskState.ENQUEUED,
            )
            ledger.create_outbox_event(task_id=task.task_id)
            second = worker.process_one()
            done = ledger.get_task(task.task_id)

            self.assertEqual(second.state, TaskState.DONE)
            self.assertEqual(done.state, TaskState.DONE)
            self.assertEqual(done.attempt_count, 2)
            self.assertEqual(transport.calls, 2)

    def test_worker_processes_replayed_dead_letter_task(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            origin = ledger.create_task(
                idempotency_key="worker-replay-origin",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            ledger.claim_next_outbox_event()
            ledger.transition_task(
                origin.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.DEAD_LETTER,
                error_json={"message": "previous failure"},
            )
            replay = ledger.replay_task(origin.task_id)
            worker = LocalWorker(
                ledger=ledger,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
                transport=FakeTransport(),
                raw_evidence_sink=FileRawEvidenceSink(Path(temp_dir) / "raw"),
            )

            result = worker.process_one()
            replay_after = ledger.get_task(replay.task_id)
            origin_after = ledger.get_task(origin.task_id)

            self.assertTrue(result.processed)
            self.assertEqual(result.task_id, replay.task_id)
            self.assertEqual(replay_after.state, TaskState.DONE)
            self.assertEqual(replay_after.replay_origin_task_id, origin.task_id)
            self.assertEqual(origin_after.state, TaskState.DEAD_LETTER)

    def test_worker_skips_cancelled_task_event(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="cancelled-worker-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            cancelled = ledger.cancel_task(task.task_id)
            worker = LocalWorker(
                ledger=ledger,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
                transport=FakeTransport(),
                raw_evidence_sink=FileRawEvidenceSink(Path(temp_dir) / "raw"),
            )

            result = worker.process_one()

            self.assertTrue(result.processed)
            self.assertEqual(result.task_id, cancelled.task_id)
            self.assertEqual(result.state, TaskState.CANCELLED)


if __name__ == "__main__":
    unittest.main()
