import os
import tempfile
import unittest
import uuid
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import redis as redis_lib

from postgres_fixture import make_postgres_ledger

from xingestion.capabilities import (
    CapabilityPlanner,
    CapabilityRequest,
    SearchTweetsInput,
)
from xingestion.dispatch import RedisOutboxDispatcher, redis_queue_stats
from xingestion.tasks import TaskState
from xingestion.workers import LocalWorker
from xingestion.xprotocol.evidence import FileRawEvidenceSink
from xingestion.xprotocol.protocol import CapabilityId, ProtocolReleaseManifest
from xingestion.xprotocol.runtime import ProtocolHttpResponse, WebSessionAuth

TEST_REDIS_URL = "redis://127.0.0.1:6379/1"

RUN_LOAD_TESTS = os.getenv("XINGESTION_RUN_LOAD_TESTS") == "1"


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


def load_manifest():
    return ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )


@unittest.skipUnless(
    RUN_LOAD_TESTS,
    "load/soak delivery tests are opt-in; set XINGESTION_RUN_LOAD_TESTS=1 to run them",
)
class DeliveryLoadTests(unittest.TestCase):
    """Drives the outbox -> Redis Streams -> consumer-group-worker path at a
    scale and crash pattern the functional tests in test_local_worker.py
    don't reach: many in-flight deliveries, several simultaneously-crashed
    consumers, and repeated cycles that would surface a slow queue leak.
    """

    def setUp(self):
        try:
            self.ledger = make_postgres_ledger()
        except Exception as exc:  # pragma: no cover - environment dependent
            self.skipTest(f"Postgres unavailable: {exc}")
        try:
            self.redis_client = redis_lib.Redis.from_url(
                TEST_REDIS_URL, decode_responses=True, socket_connect_timeout=3
            )
            self.redis_client.ping()
        except Exception as exc:  # pragma: no cover - environment dependent
            self.ledger.pool.close()
            self.skipTest(f"Redis unavailable: {exc}")

        self.redis_client.flushdb()
        self.stream_key = f"test-load-stream-{uuid.uuid4().hex[:8]}"
        self.consumer_group = "load-workers"
        self.dispatcher = RedisOutboxDispatcher(
            ledger=self.ledger,
            redis_client=self.redis_client,
            stream_key=self.stream_key,
        )
        self.manifest = load_manifest()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()
        self.redis_client.flushdb()
        self.redis_client.close()
        self.ledger.pool.close()

    def make_worker(self, owner: str, **kwargs) -> LocalWorker:
        return LocalWorker(
            ledger=self.ledger,
            manifest=self.manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / f"raw-{owner}"),
            redis_client=self.redis_client,
            redis_stream_key=self.stream_key,
            redis_consumer_group=self.consumer_group,
            redis_consumer_name=owner,
            redis_read_block_ms=50,
            **kwargs,
        )

    def create_tasks(self, count: int) -> list[str]:
        task_ids = []
        for i in range(count):
            request = CapabilityRequest(
                capability_id=CapabilityId.SEARCH_TWEETS,
                contract_version=1,
                payload=SearchTweetsInput(query=f"load-{i}", page_size=20),
            )
            plan = CapabilityPlanner(self.manifest).plan(request)
            task = self.ledger.create_task(
                idempotency_key=f"load-key-{uuid.uuid4().hex}",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            task_ids.append(task.task_id)
        return task_ids

    def dispatch_all_pending(self) -> int:
        dispatched = 0
        while self.dispatcher.dispatch_once().dispatched:
            dispatched += 1
        return dispatched

    def queue_stats(self) -> dict[str, object]:
        return redis_queue_stats(
            self.redis_client, stream_key=self.stream_key, group_name=self.consumer_group
        )

    def drain_with_workers(self, workers: list[LocalWorker], expected: int) -> int:
        processed = 0
        idle_rounds = 0
        while idle_rounds < 5 and processed < expected:
            made_progress = False
            for worker in workers:
                if worker.process_one().processed:
                    processed += 1
                    made_progress = True
            idle_rounds = 0 if made_progress else idle_rounds + 1
        return processed

    def test_many_tasks_drain_with_no_loss_or_stuck_deliveries(self):
        total = 150
        task_ids = self.create_tasks(total)
        self.assertEqual(self.dispatch_all_pending(), total)

        workers = [self.make_worker(f"worker-{i}") for i in range(4)]
        processed = self.drain_with_workers(workers, total)

        states = {task_id: self.ledger.get_task(task_id).state for task_id in task_ids}
        self.assertEqual(processed, total)
        self.assertTrue(all(state == TaskState.DONE for state in states.values()), states)

        stats = self.queue_stats()
        self.assertEqual(stats["pending_count"], 0)
        self.assertEqual(stats["lag"], 0)
        self.assertEqual(self.ledger.outbox_stats()["unpublished_events"], 0)

    def test_crash_recovery_reclaims_many_stale_deliveries_under_load(self):
        total = 30
        task_ids = self.create_tasks(total)
        self.dispatch_all_pending()

        # Three consumers each read messages (now pending in the group) and
        # then "crash" -- they never ack. Default redis_claim_min_idle_ms
        # keeps these entries out of each other's reach so all `total`
        # messages end up genuinely stuck in the PEL before recovery starts.
        crashed_workers = [self.make_worker(f"crashed-{i}") for i in range(3)]
        stale_deliveries = 0
        for i in range(total):
            delivery = crashed_workers[i % len(crashed_workers)]._read_next_delivery()
            if delivery is not None:
                stale_deliveries += 1
        self.assertEqual(stale_deliveries, total)
        self.assertEqual(self.queue_stats()["pending_count"], total)

        recovering_workers = [
            self.make_worker(f"recovering-{i}", redis_claim_min_idle_ms=0) for i in range(2)
        ]
        processed = self.drain_with_workers(recovering_workers, total)

        states = {task_id: self.ledger.get_task(task_id).state for task_id in task_ids}
        self.assertEqual(processed, total)
        self.assertTrue(all(state == TaskState.DONE for state in states.values()), states)
        self.assertEqual(self.queue_stats()["pending_count"], 0)

    def test_soak_repeated_dispatch_process_cycles_leave_no_backlog(self):
        cycles = 20
        per_cycle = 5
        for cycle in range(cycles):
            task_ids = self.create_tasks(per_cycle)
            self.dispatch_all_pending()
            worker = self.make_worker(f"soak-{cycle}")
            processed = self.drain_with_workers([worker], per_cycle)

            states = [self.ledger.get_task(task_id).state for task_id in task_ids]
            self.assertEqual(processed, per_cycle, f"cycle={cycle}")
            self.assertTrue(
                all(state == TaskState.DONE for state in states), f"cycle={cycle} states={states}"
            )
            self.assertEqual(
                self.ledger.outbox_stats()["unpublished_events"], 0, f"cycle={cycle}"
            )
            self.assertEqual(self.queue_stats()["pending_count"], 0, f"cycle={cycle}")


if __name__ == "__main__":
    unittest.main()
