import unittest
import uuid
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import redis as redis_lib

from xingestion.dispatch import reconcile_redis_stream_backlog, redis_queue_stats

TEST_REDIS_URL = "redis://127.0.0.1:6379/1"


class FakeLedger:
    def __init__(self, existing_task_ids):
        self.existing_task_ids = set(existing_task_ids)

    def get_task(self, task_id):
        return object() if task_id in self.existing_task_ids else None


class RedisQueueStatsTests(unittest.TestCase):
    def setUp(self):
        try:
            self.redis_client = redis_lib.Redis.from_url(
                TEST_REDIS_URL, decode_responses=True, socket_connect_timeout=3
            )
            self.redis_client.ping()
        except Exception as exc:  # pragma: no cover - environment dependent
            self.skipTest(f"Redis unavailable: {exc}")

        self.stream_key = f"test-stream-{uuid.uuid4().hex[:8]}"
        self.group_name = "test-workers"

    def tearDown(self):
        self.redis_client.delete(self.stream_key)
        self.redis_client.close()

    def test_reports_empty_stats_when_stream_does_not_exist_at_all(self):
        # Regression: XINFO GROUPS raises ResponseError on a key that has
        # never been written to (unlike XLEN, which happily returns 0) --
        # e.g. a fresh CI run or deployment where nothing has ever been
        # dispatched to this stream yet.
        stats = redis_queue_stats(
            self.redis_client, stream_key=self.stream_key, group_name=self.group_name
        )

        self.assertFalse(stats["group_exists"])
        self.assertEqual(stats["stream_length"], 0)
        self.assertEqual(stats["pending_count"], 0)
        self.assertIsNone(stats["lag"])
        self.assertIsNone(stats["oldest_pending_idle_ms"])

    def test_reports_group_missing_when_stream_has_no_group(self):
        self.redis_client.xadd(self.stream_key, {"task_id": "t1"})

        stats = redis_queue_stats(
            self.redis_client, stream_key=self.stream_key, group_name=self.group_name
        )

        self.assertFalse(stats["group_exists"])
        self.assertEqual(stats["stream_length"], 1)
        self.assertEqual(stats["pending_count"], 0)
        self.assertIsNone(stats["lag"])
        self.assertIsNone(stats["oldest_pending_idle_ms"])

    def test_reports_lag_with_no_pending_entries(self):
        self.redis_client.xadd(self.stream_key, {"task_id": "t1"})
        self.redis_client.xadd(self.stream_key, {"task_id": "t2"})
        self.redis_client.xgroup_create(self.stream_key, self.group_name, id="0")

        stats = redis_queue_stats(
            self.redis_client, stream_key=self.stream_key, group_name=self.group_name
        )

        self.assertTrue(stats["group_exists"])
        self.assertEqual(stats["stream_length"], 2)
        self.assertEqual(stats["pending_count"], 0)
        self.assertEqual(stats["lag"], 2)
        self.assertIsNone(stats["oldest_pending_idle_ms"])

    def test_reports_pending_count_and_oldest_idle_after_read(self):
        self.redis_client.xadd(self.stream_key, {"task_id": "t1"})
        self.redis_client.xgroup_create(self.stream_key, self.group_name, id="0")
        self.redis_client.xreadgroup(
            self.group_name, "consumer-1", {self.stream_key: ">"}, count=1
        )

        stats = redis_queue_stats(
            self.redis_client, stream_key=self.stream_key, group_name=self.group_name
        )

        self.assertTrue(stats["group_exists"])
        self.assertEqual(stats["pending_count"], 1)
        self.assertEqual(stats["lag"], 0)
        self.assertIsNotNone(stats["oldest_pending_idle_ms"])
        self.assertGreaterEqual(stats["oldest_pending_idle_ms"], 0)


class ReconcileRedisStreamBacklogTests(unittest.TestCase):
    def setUp(self):
        try:
            self.redis_client = redis_lib.Redis.from_url(
                TEST_REDIS_URL, decode_responses=True, socket_connect_timeout=3
            )
            self.redis_client.ping()
        except Exception as exc:  # pragma: no cover - environment dependent
            self.skipTest(f"Redis unavailable: {exc}")

        self.stream_key = f"test-reconcile-stream-{uuid.uuid4().hex[:8]}"

    def tearDown(self):
        self.redis_client.delete(self.stream_key)
        self.redis_client.close()

    def test_reports_no_orphans_when_every_task_exists(self):
        self.redis_client.xadd(self.stream_key, {"task_id": "task-1"})
        self.redis_client.xadd(self.stream_key, {"task_id": "task-2"})
        ledger = FakeLedger(["task-1", "task-2"])

        result = reconcile_redis_stream_backlog(
            self.redis_client, ledger, stream_key=self.stream_key
        )

        self.assertEqual(result["scanned_entries"], 2)
        self.assertEqual(result["orphaned_count"], 0)
        self.assertEqual(result["deleted_entries"], 0)
        self.assertEqual(self.redis_client.xlen(self.stream_key), 2)

    def test_dry_run_reports_orphans_without_deleting(self):
        self.redis_client.xadd(self.stream_key, {"task_id": "task-1"})
        self.redis_client.xadd(self.stream_key, {"task_id": "task-missing"})
        ledger = FakeLedger(["task-1"])

        result = reconcile_redis_stream_backlog(
            self.redis_client, ledger, stream_key=self.stream_key, dry_run=True
        )

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["scanned_entries"], 2)
        self.assertEqual(result["orphaned_count"], 1)
        self.assertEqual(result["orphaned_entries"][0]["task_id"], "task-missing")
        self.assertEqual(result["deleted_entries"], 0)
        self.assertEqual(self.redis_client.xlen(self.stream_key), 2)

    def test_apply_deletes_only_orphaned_entries(self):
        self.redis_client.xadd(self.stream_key, {"task_id": "task-1"})
        self.redis_client.xadd(self.stream_key, {"task_id": "task-missing"})
        ledger = FakeLedger(["task-1"])

        result = reconcile_redis_stream_backlog(
            self.redis_client, ledger, stream_key=self.stream_key, dry_run=False
        )

        self.assertFalse(result["dry_run"])
        self.assertEqual(result["orphaned_count"], 1)
        self.assertEqual(result["deleted_entries"], 1)
        remaining = self.redis_client.xrange(self.stream_key, min="-", max="+")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0][1]["task_id"], "task-1")

    def test_ignores_entries_without_a_task_id_field(self):
        self.redis_client.xadd(self.stream_key, {"other_field": "x"})
        ledger = FakeLedger([])

        result = reconcile_redis_stream_backlog(
            self.redis_client, ledger, stream_key=self.stream_key
        )

        self.assertEqual(result["scanned_entries"], 1)
        self.assertEqual(result["orphaned_count"], 0)

    def test_rejects_non_positive_limit(self):
        ledger = FakeLedger([])
        with self.assertRaises(ValueError):
            reconcile_redis_stream_backlog(
                self.redis_client, ledger, stream_key=self.stream_key, limit=0
            )


if __name__ == "__main__":
    unittest.main()
