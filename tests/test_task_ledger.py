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
            self.assertIsNone(reloaded.result_json)
            self.assertIsNone(reloaded.error_json)

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
            self.assertEqual(len(ledger.list_outbox_events_for_task(first.task_id)), 1)

    def test_create_task_creates_atomic_outbox_event(self):
        request, plan = make_request_and_plan()
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="outbox-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )

            events = ledger.list_outbox_events_for_task(task.task_id)

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "CAPABILITY_TASK_CREATED")
            self.assertEqual(events[0].payload_json["task_id"], task.task_id)
            self.assertIsNone(events[0].published_at)

            claimed = ledger.claim_next_outbox_event()

            self.assertEqual(claimed.event_id, events[0].event_id)
            self.assertIsNotNone(claimed.published_at)
            self.assertIsNone(ledger.claim_next_outbox_event())

    def test_due_retries_are_reenqueued_with_outbox_events(self):
        request, plan = make_request_and_plan()
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="due-retry-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            claimed = ledger.claim_next_outbox_event()
            self.assertIsNotNone(claimed)
            ledger.transition_task(
                task.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.RETRY_SCHEDULED,
                next_attempt_at="2000-01-01T00:00:00+00:00",
            )

            count = ledger.enqueue_due_retries(now="2000-01-01T00:00:01+00:00")
            reloaded = ledger.get_task(task.task_id)
            event = ledger.claim_next_outbox_event()

            self.assertEqual(count, 1)
            self.assertEqual(reloaded.state, TaskState.ENQUEUED)
            self.assertEqual(event.task_id, task.task_id)

    def test_execution_lease_sets_owner_token_and_generation(self):
        request, plan = make_request_and_plan()
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="lease-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            ledger.transition_task(
                task.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.ENQUEUED,
            )

            leased = ledger.acquire_execution_lease(
                task.task_id,
                owner="worker-a",
                lease_expires_at="2999-01-01T00:00:00+00:00",
            )

            self.assertEqual(leased.state, TaskState.RUNNING)
            self.assertEqual(leased.lease_owner, "worker-a")
            self.assertTrue(leased.lease_token.startswith("lease-"))
            self.assertEqual(leased.delivery_generation, 1)
            self.assertEqual(leased.attempt_count, 1)

    def test_fenced_transition_rejects_stale_lease_token(self):
        request, plan = make_request_and_plan()
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="stale-token-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            ledger.transition_task(
                task.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.ENQUEUED,
            )
            leased = ledger.acquire_execution_lease(
                task.task_id,
                owner="worker-a",
                lease_expires_at="2999-01-01T00:00:00+00:00",
            )

            with self.assertRaisesRegex(ValueError, "expected state"):
                ledger.transition_task(
                    task.task_id,
                    from_state=TaskState.RUNNING,
                    to_state=TaskState.DONE,
                    lease_token="lease-stale",
                    delivery_generation=leased.delivery_generation,
                    clear_lease=True,
                )

            self.assertEqual(ledger.get_task(task.task_id).state, TaskState.RUNNING)

    def test_expired_lease_is_recovered_and_reenqueued(self):
        request, plan = make_request_and_plan()
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="expired-lease-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            ledger.claim_next_outbox_event()
            ledger.transition_task(
                task.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.ENQUEUED,
            )
            ledger.acquire_execution_lease(
                task.task_id,
                owner="worker-a",
                lease_expires_at="2000-01-01T00:00:00+00:00",
            )

            recovered = ledger.recover_expired_leases(now="2000-01-01T00:00:01+00:00")
            task_after = ledger.get_task(task.task_id)
            event = ledger.claim_next_outbox_event()

            self.assertEqual(recovered, 1)
            self.assertEqual(task_after.state, TaskState.ENQUEUED)
            self.assertIsNone(task_after.lease_token)
            self.assertEqual(event.event_type, "CAPABILITY_TASK_LEASE_EXPIRED")
            self.assertEqual(event.task_id, task.task_id)

    def test_replay_dead_letter_task_creates_new_queued_origin(self):
        request, plan = make_request_and_plan()
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="dead-letter-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            dead = ledger.transition_task(
                task.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.DEAD_LETTER,
                error_json={"message": "auth failed"},
            )

            replay = ledger.replay_task(dead.task_id)
            origin = ledger.get_task(dead.task_id)
            events = ledger.list_outbox_events_for_task(replay.task_id)

            self.assertEqual(origin.state, TaskState.DEAD_LETTER)
            self.assertEqual(replay.state, TaskState.CREATED)
            self.assertEqual(replay.replay_origin_task_id, dead.task_id)
            self.assertEqual(replay.request_json, dead.request_json)
            self.assertEqual(replay.plan_json, dead.plan_json)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "CAPABILITY_TASK_REPLAY_CREATED")
            self.assertEqual(events[0].payload_json["task_id"], replay.task_id)
            self.assertEqual(events[0].payload_json["origin_task_id"], dead.task_id)

    def test_replay_rejects_non_dead_letter_task(self):
        request, plan = make_request_and_plan()
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="not-dead-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )

            with self.assertRaisesRegex(ValueError, "Only DEAD_LETTER"):
                ledger.replay_task(task.task_id)

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
            done = ledger.transition_task(
                task.task_id,
                from_state=TaskState.ENQUEUED,
                to_state=TaskState.DONE,
                result_json={"raw_evidence": {"storage_uri": "x"}},
            )

            self.assertEqual(done.result_json["raw_evidence"]["storage_uri"], "x")
            with self.assertRaisesRegex(ValueError, "expected state"):
                ledger.transition_task(
                    task.task_id,
                    from_state=TaskState.CREATED,
                    to_state=TaskState.RUNNING,
                )


if __name__ == "__main__":
    unittest.main()
