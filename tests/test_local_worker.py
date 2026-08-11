import tempfile
import unittest
from datetime import UTC, datetime, timedelta
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
from xingestion.canonical import CanonicalStore
from xingestion.releases import ReleaseHealth, ReleaseStore
from xingestion.sessions import SessionHealth, SessionStore
from xingestion.telemetry import ProtocolTelemetryStore
from xingestion.workers import LocalWorker
from xrev.evidence import FileRawEvidenceSink
from xrev.protocol import CapabilityId, ProtocolReleaseManifest
from xrev.runtime import ProtocolError, ProtocolHttpResponse, WebSessionAuth
from xrev.runtime.transport import RetryDisposition


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


class CursorTransport(FakeTransport):
    def send(self, request):
        response = super().send(request)
        body = dict(response.json_body)
        body["cursorType"] = "Bottom"
        body["value"] = "cursor-next"
        return ProtocolHttpResponse(response.status_code, body)


class FlakyTransport:
    def __init__(self):
        self.calls = 0

    def send(self, request):
        self.calls += 1
        if self.calls == 1:
            return ProtocolHttpResponse(500, {"errors": ["temporary"]})
        return FakeTransport().send(request)


class AuthRejectedTransport:
    def send(self, request):
        return ProtocolHttpResponse(401, {"errors": ["auth rejected"]})


class RateLimitedTransport:
    def send(self, request):
        return ProtocolHttpResponse(429, {"errors": ["rate limited"]}, {"retry-after": "120"})


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
            self.assertEqual(result.lease_renewals, 2)
            self.assertIsNotNone(result.raw_evidence_ref)
            self.assertEqual(reloaded.state, TaskState.DONE)
            self.assertEqual(
                reloaded.result_json["raw_evidence"]["evidence_id"],
                result.raw_evidence_ref.evidence_id,
            )
            self.assertIsNone(worker.process_one().task_id)

    def test_worker_persists_canonical_tweets_on_success(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            ledger = SQLiteTaskLedger(db_path)
            store = CanonicalStore(db_path)
            task = ledger.create_task(
                idempotency_key="canonical-worker-key",
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
                canonical_store=store,
            )

            worker.process_one()

            self.assertEqual(store.counts()["canonical_tweets"], 1)
            self.assertEqual(store.counts()["engagement_observations"], 1)
            self.assertEqual(store.get_tweet("1").username, "alice")
            self.assertEqual(ledger.get_task(task.task_id).state, TaskState.DONE)

    def test_worker_acquires_and_releases_session_lease(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            ledger = SQLiteTaskLedger(db_path)
            sessions = SessionStore(db_path)
            sessions.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
                network_context="direct",
            )
            task = ledger.create_task(
                idempotency_key="session-worker-key",
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
                session_store=sessions,
            )

            result = worker.process_one()
            session_after = sessions.get_session("session-1")
            task_after = ledger.get_task(task.task_id)

            self.assertEqual(result.state, TaskState.DONE)
            self.assertEqual(result.session_id, "session-1")
            self.assertIsNone(session_after.lease_token)
            self.assertEqual(session_after.attempt_count, 1)
            self.assertEqual(session_after.success_count, 1)
            self.assertEqual(session_after.failure_count, 0)
            self.assertIsNotNone(session_after.last_attempt_at)
            self.assertIsNotNone(session_after.last_success_at)
            self.assertEqual(task_after.result_json["session"]["session_id"], "session-1")
            self.assertEqual(task_after.result_json["session"]["network_context"], "direct")

    def test_worker_records_success_telemetry(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            ledger = SQLiteTaskLedger(db_path)
            telemetry = ProtocolTelemetryStore(db_path)
            task = ledger.create_task(
                idempotency_key="telemetry-success-key",
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
                telemetry_store=telemetry,
            )

            worker.process_one()
            summary = telemetry.summary()

            self.assertEqual(summary.total_attempts, 1)
            self.assertEqual(summary.successes, 1)
            self.assertEqual(summary.failures, 0)

    def test_worker_records_failure_telemetry(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            ledger = SQLiteTaskLedger(db_path)
            telemetry = ProtocolTelemetryStore(db_path)
            ledger.create_task(
                idempotency_key="telemetry-failure-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            worker = LocalWorker(
                ledger=ledger,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
                transport=AuthRejectedTransport(),
                raw_evidence_sink=FileRawEvidenceSink(Path(temp_dir) / "raw"),
                telemetry_store=telemetry,
            )

            worker.process_one()
            summary = telemetry.summary()

            self.assertEqual(summary.total_attempts, 1)
            self.assertEqual(summary.successes, 0)
            self.assertEqual(summary.failures, 1)
            self.assertEqual(summary.errors_by_class["AUTH_OR_SESSION_REJECTED"], 1)

    def test_worker_schedules_retry_when_no_healthy_session_available(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            ledger = SQLiteTaskLedger(db_path)
            sessions = SessionStore(db_path)
            sessions.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
                health=SessionHealth.AUTH_EXPIRED,
            )
            task = ledger.create_task(
                idempotency_key="session-unavailable-key",
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
                session_store=sessions,
            )

            result = worker.process_one()
            task_after = ledger.get_task(task.task_id)

            self.assertEqual(result.state, TaskState.RETRY_SCHEDULED)
            self.assertEqual(result.error_class, "SESSION_UNAVAILABLE")
            self.assertEqual(task_after.error_json["error_class"], "SESSION_UNAVAILABLE")
            self.assertIsNotNone(task_after.next_attempt_at)

    def test_worker_marks_session_auth_expired_on_auth_rejection(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            ledger = SQLiteTaskLedger(db_path)
            sessions = SessionStore(db_path)
            sessions.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )
            task = ledger.create_task(
                idempotency_key="session-auth-expired-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            worker = LocalWorker(
                ledger=ledger,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
                transport=AuthRejectedTransport(),
                raw_evidence_sink=FileRawEvidenceSink(Path(temp_dir) / "raw"),
                session_store=sessions,
            )

            result = worker.process_one()
            task_after = ledger.get_task(task.task_id)
            session_after = sessions.get_session("session-1")

            self.assertEqual(result.state, TaskState.DEAD_LETTER)
            self.assertEqual(result.error_class, "AUTH_OR_SESSION_REJECTED")
            self.assertEqual(
                task_after.error_json["runtime_error"]["operator_action"],
                "restore_or_replace_x_session_credentials",
            )
            self.assertEqual(task_after.error_json["runtime_error"]["severity"], "HIGH")
            self.assertEqual(task_after.error_json["runtime_error"]["scope"], "SESSION")
            self.assertEqual(session_after.health, SessionHealth.AUTH_EXPIRED)
            self.assertIsNone(session_after.lease_token)
            self.assertEqual(session_after.attempt_count, 1)
            self.assertEqual(session_after.success_count, 0)
            self.assertEqual(session_after.failure_count, 1)
            self.assertEqual(session_after.last_error_class, "AUTH_OR_SESSION_REJECTED")
            self.assertEqual(session_after.last_error_message, "X returned HTTP 401")

    def test_worker_marks_session_degraded_on_rate_limit(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            ledger = SQLiteTaskLedger(db_path)
            sessions = SessionStore(db_path)
            sessions.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )
            ledger.create_task(
                idempotency_key="session-rate-limit-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            worker = LocalWorker(
                ledger=ledger,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
                transport=RateLimitedTransport(),
                raw_evidence_sink=FileRawEvidenceSink(Path(temp_dir) / "raw"),
                session_store=sessions,
            )

            result = worker.process_one()
            session_after = sessions.get_session("session-1")

            self.assertEqual(result.state, TaskState.RETRY_SCHEDULED)
            self.assertEqual(result.error_class, "RATE_LIMITED")
            self.assertEqual(session_after.health, SessionHealth.DEGRADED)
            self.assertEqual(session_after.attempt_count, 1)
            self.assertEqual(session_after.success_count, 0)
            self.assertEqual(session_after.failure_count, 1)
            self.assertEqual(session_after.last_error_class, "RATE_LIMITED")
            self.assertIsNotNone(session_after.cooldown_until)
            self.assertGreater(
                datetime.fromisoformat(session_after.cooldown_until),
                datetime.now(UTC),
            )
            self.assertIsNone(sessions.acquire_session(owner="worker-b", lease_seconds=60))

    def test_worker_restores_degraded_session_after_successful_cooldown_retry(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            ledger = SQLiteTaskLedger(db_path)
            sessions = SessionStore(db_path)
            sessions.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )
            sessions.update_health(
                "session-1",
                health=SessionHealth.DEGRADED,
                reason="cooldown elapsed",
                cooldown_until=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            )
            ledger.create_task(
                idempotency_key="session-cooldown-success-key",
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
                session_store=sessions,
            )

            result = worker.process_one()
            session_after = sessions.get_session("session-1")

            self.assertEqual(result.state, TaskState.DONE)
            self.assertEqual(session_after.health, SessionHealth.HEALTHY)
            self.assertIsNone(session_after.cooldown_until)

    def test_worker_queues_bounded_cursor_continuation(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20, max_pages=2),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            ledger = SQLiteTaskLedger(db_path)
            task = ledger.create_task(
                idempotency_key="pagination-root",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            worker = LocalWorker(
                ledger=ledger,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
                transport=CursorTransport(),
                raw_evidence_sink=FileRawEvidenceSink(Path(temp_dir) / "raw"),
            )

            result = worker.process_one()
            root = ledger.get_task(task.task_id)
            continuation_id = root.result_json["pagination"]["continuation_task_id"]
            continuation = ledger.get_task(continuation_id)

            self.assertEqual(result.state, TaskState.DONE)
            self.assertEqual(root.result_json["pagination"]["next_cursor"], "cursor-next")
            self.assertEqual(continuation.state, TaskState.CREATED)
            self.assertEqual(continuation.request_json["payload"]["cursor"], "cursor-next")
            self.assertEqual(continuation.request_json["payload"]["page_number"], 2)
            self.assertEqual(
                continuation.request_json["payload"]["pagination_root_task_id"],
                task.task_id,
            )
            self.assertEqual(
                continuation.request_json["payload"]["pagination_parent_task_id"],
                task.task_id,
            )

    def test_worker_does_not_continue_after_max_pages(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(
                query="india",
                cursor="cursor-current",
                page_size=20,
                max_pages=2,
                page_number=2,
                pagination_root_task_id="task-root",
                pagination_parent_task_id="task-parent",
            ),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="pagination-final",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            worker = LocalWorker(
                ledger=ledger,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
                transport=CursorTransport(),
                raw_evidence_sink=FileRawEvidenceSink(Path(temp_dir) / "raw"),
            )

            worker.process_one()
            final = ledger.get_task(task.task_id)

            self.assertIsNone(final.result_json["pagination"]["continuation_task_id"])
            self.assertEqual(final.result_json["pagination"]["page_number"], 2)

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

    def test_worker_dead_letters_when_release_is_quarantined(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            ledger = SQLiteTaskLedger(db_path)
            release_store = ReleaseStore(db_path)
            release_store.set_health(
                manifest.release_id,
                health=ReleaseHealth.QUARANTINED,
                reason="test quarantine",
            )
            task = ledger.create_task(
                idempotency_key="quarantine-key",
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
                release_store=release_store,
            )

            result = worker.process_one()
            reloaded = ledger.get_task(task.task_id)

            self.assertEqual(result.state, TaskState.DEAD_LETTER)
            self.assertEqual(result.error_class, "PROTOCOL_RELEASE_BLOCKED")
            self.assertEqual(reloaded.error_json["error_class"], "PROTOCOL_RELEASE_BLOCKED")


if __name__ == "__main__":
    unittest.main()
