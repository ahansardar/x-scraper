import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from postgres_fixture import make_postgres_ledger

from xingestion.capabilities import (
    CapabilityPlanner,
    CapabilityRequest,
    SearchTweetsInput,
)
from xingestion.tasks import TaskState
from xingestion.xprotocol.protocol import CapabilityId, ProtocolReleaseManifest


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


class PostgresTaskLedgerTests(unittest.TestCase):
    def setUp(self):
        try:
            self.ledger = make_postgres_ledger()
        except Exception as exc:  # pragma: no cover - environment dependent
            self.skipTest(f"Postgres unavailable: {exc}")

    def tearDown(self):
        pool = getattr(self, "ledger", None)
        if pool is not None:
            pool.pool.close()

    def test_creates_and_reloads_durable_task(self):
        request, plan = make_request_and_plan()
        ledger = self.ledger
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
        ledger = self.ledger
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
        ledger = self.ledger
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
        ledger = self.ledger
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
        ledger = self.ledger
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
        ledger = self.ledger
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

    def test_renew_execution_lease_requires_current_token_and_generation(self):
        request, plan = make_request_and_plan()
        ledger = self.ledger
        task = ledger.create_task(
            idempotency_key="renew-lease-key",
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

        renewed = ledger.renew_execution_lease(
            task.task_id,
            lease_token=leased.lease_token,
            delivery_generation=leased.delivery_generation,
            lease_expires_at="2999-01-01T00:10:00+00:00",
        )

        self.assertEqual(renewed.lease_expires_at, "2999-01-01T00:10:00+00:00")
        with self.assertRaisesRegex(ValueError, "renew execution lease"):
            ledger.renew_execution_lease(
                task.task_id,
                lease_token="lease-stale",
                delivery_generation=leased.delivery_generation,
                lease_expires_at="2999-01-01T00:20:00+00:00",
            )

    def test_expired_lease_is_recovered_and_reenqueued(self):
        request, plan = make_request_and_plan()
        ledger = self.ledger
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
        ledger = self.ledger
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
        ledger = self.ledger
        task = ledger.create_task(
            idempotency_key="not-dead-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )

        with self.assertRaisesRegex(ValueError, "Only DEAD_LETTER"):
            ledger.replay_task(task.task_id)

    def test_cancel_pending_task_sets_terminal_state(self):
        request, plan = make_request_and_plan()
        ledger = self.ledger
        task = ledger.create_task(
            idempotency_key="cancel-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )

        cancelled = ledger.cancel_task(task.task_id)

        self.assertEqual(cancelled.state, TaskState.CANCELLED)
        self.assertEqual(cancelled.error_json["reason"], "operator_cancelled")
        with self.assertRaisesRegex(ValueError, "expected state CREATED"):
            ledger.transition_task(
                task.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.ENQUEUED,
            )

    def test_cancel_rejects_completed_task(self):
        request, plan = make_request_and_plan()
        ledger = self.ledger
        task = ledger.create_task(
            idempotency_key="cancel-done-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        ledger.transition_task(
            task.task_id,
            from_state=TaskState.CREATED,
            to_state=TaskState.DONE,
            result_json={"raw_evidence": {"storage_uri": "x"}},
        )

        with self.assertRaisesRegex(ValueError, "can be cancelled"):
            ledger.cancel_task(task.task_id)

    def test_retention_deletes_only_old_done_and_cancelled_tasks(self):
        request, plan = make_request_and_plan()
        ledger = self.ledger
        done = ledger.create_task(
            idempotency_key="old-done-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        cancelled = ledger.create_task(
            idempotency_key="old-cancelled-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        dead = ledger.create_task(
            idempotency_key="old-dead-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        ledger.transition_task(
            done.task_id,
            from_state=TaskState.CREATED,
            to_state=TaskState.DONE,
            result_json={"raw_evidence": {"storage_uri": "x"}},
        )
        ledger.cancel_task(cancelled.task_id)
        ledger.transition_task(
            dead.task_id,
            from_state=TaskState.CREATED,
            to_state=TaskState.DEAD_LETTER,
            error_json={"message": "keep me"},
        )
        with ledger.pool.connection() as conn:
            conn.execute("UPDATE capability_tasks SET updated_at = %s", ("2000-01-01T00:00:00+00:00",))
            conn.commit()

        dry_run = ledger.apply_retention(days=1, dry_run=True)
        result = ledger.apply_retention(days=1, dry_run=False)

        self.assertEqual(dry_run.matched_tasks, 2)
        self.assertEqual(dry_run.deleted_tasks, 0)
        self.assertEqual(result.deleted_tasks, 2)
        self.assertIsNone(ledger.get_task(done.task_id))
        self.assertIsNone(ledger.get_task(cancelled.task_id))
        self.assertIsNotNone(ledger.get_task(dead.task_id))

    def test_task_state_counts_and_outbox_stats(self):
        request, plan = make_request_and_plan()
        ledger = self.ledger
        task = ledger.create_task(
            idempotency_key="metrics-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )

        counts = ledger.task_state_counts()
        outbox = ledger.outbox_stats()

        self.assertEqual(counts["CREATED"], 1)
        self.assertEqual(counts["DONE"], 0)
        self.assertEqual(outbox["unpublished_events"], 1)
        self.assertIsNotNone(outbox["oldest_unpublished_at"])
        self.assertGreaterEqual(outbox["oldest_unpublished_lag_seconds"], 0)
        events = ledger.list_unpublished_outbox_events(limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].task_id, task.task_id)

        ledger.claim_next_outbox_event()
        self.assertEqual(ledger.outbox_stats()["unpublished_events"], 0)
        self.assertEqual(ledger.list_unpublished_outbox_events(), ())

    def test_active_task_count_can_filter_by_capability(self):
        request, plan = make_request_and_plan()
        ledger = self.ledger
        task = ledger.create_task(
            idempotency_key="active-count-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )

        self.assertEqual(
            ledger.active_task_count(capability_id=CapabilityId.SEARCH_TWEETS),
            1,
        )
        ledger.transition_task(
            task.task_id,
            from_state=TaskState.CREATED,
            to_state=TaskState.DONE,
            result_json={"raw_evidence": {"storage_uri": "x"}},
        )
        self.assertEqual(
            ledger.active_task_count(capability_id=CapabilityId.SEARCH_TWEETS),
            0,
        )

    def test_state_transition_requires_expected_current_state(self):
        request, plan = make_request_and_plan()
        ledger = self.ledger
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

    def test_list_recent_task_errors_and_done_ids_for_release(self):
        request, plan = make_request_and_plan()
        ledger = self.ledger
        task = ledger.create_task(
            idempotency_key="bypass-close-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        ledger.transition_task(
            task.task_id,
            from_state=TaskState.CREATED,
            to_state=TaskState.DEAD_LETTER,
            error_json={"message": "boom"},
        )

        errors = ledger.list_recent_task_errors(limit=10)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].task_id, task.task_id)

        done_task = ledger.create_task(
            idempotency_key="done-for-release-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        ledger.transition_task(
            done_task.task_id,
            from_state=TaskState.CREATED,
            to_state=TaskState.DONE,
            result_json={"raw_evidence": {"storage_uri": "x"}},
        )

        done_ids = ledger.list_done_task_ids_for_release(
            release_id=plan.release_id, limit=10
        )
        self.assertIn(done_task.task_id, done_ids)


if __name__ == "__main__":
    unittest.main()
