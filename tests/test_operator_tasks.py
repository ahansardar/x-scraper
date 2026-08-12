import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from postgres_fixture import make_postgres_ledger

from xingestion.capabilities import CapabilityPlanner, CapabilityRequest, SearchTweetsInput
from xingestion.operator_tasks import list_operator_task_actions
from xingestion.tasks import TaskLedger, TaskState
from xingestion.xprotocol.protocol import CapabilityId, ProtocolReleaseManifest


def load_manifest():
    return ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )


class OperatorTasksTests(unittest.TestCase):
    def setUp(self):
        try:
            self.ledger = make_postgres_ledger()
        except Exception as exc:  # pragma: no cover - environment dependent
            self.skipTest(f"Postgres unavailable: {exc}")

    def tearDown(self):
        self.ledger.pool.close()

    def test_lists_failed_tasks_with_recommended_action(self):
        manifest = load_manifest()
        ledger = self.ledger
        failed = _create_task(ledger, manifest, "failed")
        ledger.transition_task(
            failed.task_id,
            from_state=TaskState.CREATED,
            to_state=TaskState.DEAD_LETTER,
            error_json={
                "error_class": "OPERATION_NOT_FOUND",
                "message": "X returned HTTP 404 for the pinned operation",
            },
        )

        actions = list_operator_task_actions(ledger.pool)

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].task_id, failed.task_id)
        self.assertEqual(actions[0].state, "DEAD_LETTER")
        self.assertEqual(actions[0].severity, "CRITICAL")
        self.assertTrue(actions[0].replayable)
        self.assertTrue(actions[0].exportable)
        self.assertIn("investigate_protocol_release", actions[0].operator_action)

    def test_lists_retry_scheduled_task_as_cancellable(self):
        manifest = load_manifest()
        ledger = self.ledger
        task = _create_task(ledger, manifest, "retry")
        ledger.transition_task(
            task.task_id,
            from_state=TaskState.CREATED,
            to_state=TaskState.RETRY_SCHEDULED,
            error_json={
                "error_class": "SESSION_UNAVAILABLE",
                "message": "No healthy session lease is available",
            },
            next_attempt_at="2026-08-11T18:00:00+00:00",
        )

        actions = list_operator_task_actions(
            ledger.pool,
            states=(TaskState.RETRY_SCHEDULED,),
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].scope, "SESSION")
        self.assertTrue(actions[0].retryable)
        self.assertTrue(actions[0].cancellable)
        self.assertFalse(actions[0].replayable)
        self.assertIn("wait_for_retry_or_cancel", actions[0].operator_action)


def _create_task(ledger: TaskLedger, manifest: ProtocolReleaseManifest, key: str):
    request = CapabilityRequest(
        capability_id=CapabilityId.SEARCH_TWEETS,
        contract_version=1,
        payload=SearchTweetsInput(query="india", page_size=20),
    )
    plan = CapabilityPlanner(manifest).plan(request)
    return ledger.create_task(
        idempotency_key=key,
        capability_id=request.capability_id,
        contract_version=request.contract_version,
        request_json=request.public_dict(),
        plan_json=plan.public_dict(),
    )


if __name__ == "__main__":
    unittest.main()
