import tempfile
import unittest
import uuid
from datetime import UTC, datetime, timedelta
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
from xingestion.tasks import TaskState
from xingestion.canonical import CanonicalStore
from xingestion.dispatch import RedisOutboxDispatcher
from xingestion.releases import ReleaseHealth, ReleaseStore
from xingestion.sessions import SessionHealth, SessionStore
from xingestion.telemetry import ProtocolTelemetryStore
from xingestion.workers import LocalWorker
from xingestion.xprotocol.evidence import FileRawEvidenceSink
from xingestion.xprotocol.protocol import CapabilityId, ProtocolReleaseManifest
from xingestion.xprotocol.runtime import ProtocolError, ProtocolHttpResponse, WebSessionAuth
from xingestion.xprotocol.runtime.transport import RetryDisposition

TEST_REDIS_URL = "redis://127.0.0.1:6379/1"


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


class CapturingTransport(FakeTransport):
    def __init__(self):
        self.authorization = None
        self.cookie = None

    def send(self, request):
        self.authorization = request.headers["authorization"]
        self.cookie = request.headers["cookie"]
        return super().send(request)


class MappingSecretProvider:
    provider_name = "mapping"

    def __init__(self, refs):
        self.refs = refs

    def resolve_web_session_auth(self, credential_ref):
        return self.refs[credential_ref]


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
        self.stream_key = f"test-stream-{uuid.uuid4().hex[:8]}"
        self.consumer_group = "test-workers"
        self.dispatcher = RedisOutboxDispatcher(
            ledger=self.ledger,
            redis_client=self.redis_client,
            stream_key=self.stream_key,
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "aux.sqlite3"

    def tearDown(self):
        self.temp_dir.cleanup()
        self.redis_client.flushdb()
        self.redis_client.close()
        self.ledger.pool.close()

    def make_worker(self, **kwargs) -> LocalWorker:
        return LocalWorker(
            ledger=self.ledger,
            redis_client=self.redis_client,
            redis_stream_key=self.stream_key,
            redis_consumer_group=self.consumer_group,
            redis_read_block_ms=200,
            **kwargs,
        )

    def dispatch_pending(self, count: int = 1) -> None:
        for _ in range(count):
            result = self.dispatcher.dispatch_once()
            self.assertTrue(result.dispatched, "expected a pending outbox event to dispatch")

    def test_worker_claims_outbox_and_completes_task(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        task = self.ledger.create_task(
            idempotency_key="worker-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        reloaded = self.ledger.get_task(task.task_id)

        self.assertTrue(result.processed)
        self.assertEqual(result.state, TaskState.DONE)
        self.assertEqual(result.lease_renewals, 2)
        self.assertIsNotNone(result.raw_evidence_ref)
        self.assertEqual(reloaded.state, TaskState.DONE)
        self.assertEqual(
            reloaded.result_json["raw_evidence"]["evidence_id"],
            result.raw_evidence_ref.evidence_id,
        )
        self.assertFalse(worker.process_one().processed)

    def test_worker_rejects_task_planned_for_unapproved_release(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request).public_dict()
        plan["release_id"] = "not-approved-release"

        task = self.ledger.create_task(
            idempotency_key="worker-release-mismatch",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan,
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        failed = self.ledger.get_task(task.task_id)

        self.assertTrue(result.processed)
        self.assertEqual(result.error_class, "PROTOCOL_RELEASE_MISMATCH")
        self.assertEqual(failed.state, TaskState.DEAD_LETTER)
        self.assertEqual(failed.error_json["approved_release_id"], manifest.release_id)

    def test_worker_resolves_auth_from_leased_session_reference(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        session_store = SessionStore(self.db_path)
        session_store.upsert_session(
            session_id="session-a",
            account_label="account",
            credential_ref="file:session-a",
        )
        task = self.ledger.create_task(
            idempotency_key="worker-session-secret",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        transport = CapturingTransport()
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("default-auth", "default-csrf", "default-bearer"),
            secret_provider=MappingSecretProvider(
                {"file:session-a": WebSessionAuth("sa", "sc", "sb")}
            ),
            transport=transport,
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            session_store=session_store,
        )
        self.dispatch_pending(1)

        result = worker.process_one()

        self.assertEqual(result.state, TaskState.DONE)
        self.assertEqual(result.session_id, "session-a")
        self.assertEqual(transport.authorization, "Bearer sb")
        self.assertIn("auth_" + "token=sa", transport.cookie)
        self.assertIn("ct" + "0=sc", transport.cookie)
        self.assertEqual(self.ledger.get_task(task.task_id).state, TaskState.DONE)

    def test_worker_marks_session_auth_expired_when_reference_is_incomplete(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        session_store = SessionStore(self.db_path)
        session_store.upsert_session(
            session_id="session-a",
            account_label="account",
            credential_ref="file:session-a",
        )
        task = self.ledger.create_task(
            idempotency_key="worker-session-secret-missing",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        transport = CapturingTransport()
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("default-auth", "default-csrf", "default-bearer"),
            secret_provider=MappingSecretProvider(
                {"file:session-a": WebSessionAuth("", "", "")}
            ),
            transport=transport,
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            session_store=session_store,
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        session = session_store.get_session("session-a")

        self.assertEqual(result.state, TaskState.RETRY_SCHEDULED)
        self.assertEqual(result.error_class, "AUTH_OR_SESSION_REJECTED")
        self.assertEqual(session.health, SessionHealth.AUTH_EXPIRED)
        self.assertIsNone(session.lease_token)
        self.assertIsNone(transport.authorization)
        self.assertEqual(self.ledger.get_task(task.task_id).state, TaskState.RETRY_SCHEDULED)

    def test_worker_persists_canonical_tweets_on_success(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        store = CanonicalStore(self.db_path)
        task = self.ledger.create_task(
            idempotency_key="canonical-worker-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            canonical_store=store,
        )
        self.dispatch_pending(1)

        worker.process_one()

        self.assertEqual(store.counts()["canonical_tweets"], 1)
        self.assertEqual(store.counts()["engagement_observations"], 1)
        self.assertEqual(store.get_tweet("1").username, "alice")
        self.assertEqual(self.ledger.get_task(task.task_id).state, TaskState.DONE)

    def test_worker_acquires_and_releases_session_lease(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        sessions = SessionStore(self.db_path)
        sessions.upsert_session(
            session_id="session-1",
            account_label="account",
            credential_ref="secret:x/session-1",
            network_context="direct",
        )
        task = self.ledger.create_task(
            idempotency_key="session-worker-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            session_store=sessions,
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        session_after = sessions.get_session("session-1")
        task_after = self.ledger.get_task(task.task_id)

        self.assertEqual(result.state, TaskState.DONE)
        self.assertEqual(result.session_id, "session-1")
        self.assertEqual(result.network_context, "direct")
        self.assertIsNone(session_after.lease_token)
        self.assertEqual(session_after.attempt_count, 1)
        self.assertEqual(session_after.success_count, 1)
        self.assertEqual(session_after.failure_count, 0)
        self.assertIsNotNone(session_after.last_attempt_at)
        self.assertIsNotNone(session_after.last_success_at)
        self.assertEqual(task_after.result_json["session"]["session_id"], "session-1")
        self.assertEqual(task_after.result_json["session"]["network_context"], "direct")
        self.assertEqual(task_after.result_json["session"]["network_policy"]["kind"], "direct")

    def test_worker_respects_required_network_context(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        sessions = SessionStore(self.db_path)
        sessions.upsert_session(
            session_id="session-direct",
            account_label="direct-account",
            credential_ref="secret:x/direct",
            network_context="direct:iad",
        )
        sessions.upsert_session(
            session_id="session-proxy",
            account_label="proxy-account",
            credential_ref="secret:x/proxy",
            network_context="proxy:pool-a:iad",
        )
        task = self.ledger.create_task(
            idempotency_key="session-worker-network-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            session_store=sessions,
            required_network_context="proxy:pool-a",
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        task_after = self.ledger.get_task(task.task_id)

        self.assertEqual(result.state, TaskState.DONE)
        self.assertEqual(result.session_id, "session-proxy")
        self.assertEqual(result.network_context, "proxy:pool-a:iad")
        self.assertEqual(
            task_after.result_json["session"]["network_policy"]["route"],
            "pool-a",
        )

    def test_worker_retries_when_required_network_has_no_session(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        sessions = SessionStore(self.db_path)
        sessions.upsert_session(
            session_id="session-direct",
            account_label="direct-account",
            credential_ref="secret:x/direct",
            network_context="direct:iad",
        )
        task = self.ledger.create_task(
            idempotency_key="session-worker-network-miss",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            session_store=sessions,
            required_network_context="proxy:pool-a",
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        task_after = self.ledger.get_task(task.task_id)

        self.assertEqual(result.state, TaskState.RETRY_SCHEDULED)
        self.assertEqual(result.error_class, "SESSION_UNAVAILABLE")
        self.assertIn("proxy:pool-a", result.message)
        self.assertIn("proxy:pool-a", task_after.error_json["message"])

    def test_worker_records_success_telemetry(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        telemetry = ProtocolTelemetryStore(self.db_path)
        task = self.ledger.create_task(
            idempotency_key="telemetry-success-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            telemetry_store=telemetry,
        )
        self.dispatch_pending(1)

        worker.process_one()
        summary = telemetry.summary()

        self.assertEqual(summary.total_attempts, 1)
        self.assertEqual(summary.successes, 1)
        self.assertEqual(summary.failures, 0)
        attempts = telemetry.list_for_task(task.task_id)
        self.assertEqual(attempts[0].network_context, None)

    def test_worker_records_failure_telemetry(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        telemetry = ProtocolTelemetryStore(self.db_path)
        self.ledger.create_task(
            idempotency_key="telemetry-failure-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=AuthRejectedTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            telemetry_store=telemetry,
        )
        self.dispatch_pending(1)

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

        sessions = SessionStore(self.db_path)
        sessions.upsert_session(
            session_id="session-1",
            account_label="account",
            credential_ref="secret:x/session-1",
            health=SessionHealth.AUTH_EXPIRED,
        )
        task = self.ledger.create_task(
            idempotency_key="session-unavailable-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            session_store=sessions,
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        task_after = self.ledger.get_task(task.task_id)

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

        sessions = SessionStore(self.db_path)
        sessions.upsert_session(
            session_id="session-1",
            account_label="account",
            credential_ref="secret:x/session-1",
        )
        task = self.ledger.create_task(
            idempotency_key="session-auth-expired-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=AuthRejectedTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            session_store=sessions,
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        task_after = self.ledger.get_task(task.task_id)
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

        sessions = SessionStore(self.db_path)
        sessions.upsert_session(
            session_id="session-1",
            account_label="account",
            credential_ref="secret:x/session-1",
        )
        self.ledger.create_task(
            idempotency_key="session-rate-limit-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=RateLimitedTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            session_store=sessions,
        )
        self.dispatch_pending(1)

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

        sessions = SessionStore(self.db_path)
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
        self.ledger.create_task(
            idempotency_key="session-cooldown-success-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            session_store=sessions,
        )
        self.dispatch_pending(1)

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

        task = self.ledger.create_task(
            idempotency_key="pagination-root",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=CursorTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        root = self.ledger.get_task(task.task_id)
        continuation_id = root.result_json["pagination"]["continuation_task_id"]
        continuation = self.ledger.get_task(continuation_id)

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

    def test_worker_fails_when_continuation_cursor_is_missing(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20, max_pages=2),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        task = self.ledger.create_task(
            idempotency_key="pagination-missing-cursor",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        failed = self.ledger.get_task(task.task_id)

        self.assertEqual(result.state, TaskState.DEAD_LETTER)
        self.assertEqual(result.error_class, "PAGINATION_CURSOR_MISSING")
        self.assertEqual(failed.state, TaskState.DEAD_LETTER)
        self.assertEqual(failed.error_json["error_class"], "PAGINATION_CURSOR_MISSING")

    def test_pagination_failure_does_not_record_success_or_ingest_canonical(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20, max_pages=2),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        sessions = SessionStore(self.db_path)
        canonical = CanonicalStore(self.db_path)
        sessions.upsert_session(
            session_id="session-1",
            account_label="account",
            credential_ref="secret:x/session-1",
            network_context="direct",
        )
        self.ledger.create_task(
            idempotency_key="pagination-missing-cursor-side-effects",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            session_store=sessions,
            canonical_store=canonical,
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        session_after = sessions.get_session("session-1")

        self.assertEqual(result.state, TaskState.DEAD_LETTER)
        self.assertEqual(result.error_class, "PAGINATION_CURSOR_MISSING")
        self.assertEqual(session_after.attempt_count, 1)
        self.assertEqual(session_after.success_count, 0)
        self.assertEqual(session_after.failure_count, 1)
        self.assertEqual(canonical.counts()["canonical_tweets"], 0)
        self.assertEqual(canonical.counts()["engagement_observations"], 0)

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

        task = self.ledger.create_task(
            idempotency_key="pagination-final",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=CursorTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
        )
        self.dispatch_pending(1)

        worker.process_one()
        final = self.ledger.get_task(task.task_id)

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

        task = self.ledger.create_task(
            idempotency_key="retry-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        transport = FlakyTransport()
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=transport,
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
        )
        self.dispatch_pending(1)

        first = worker.process_one()
        scheduled = self.ledger.get_task(task.task_id)

        self.assertEqual(first.state, TaskState.RETRY_SCHEDULED)
        self.assertEqual(scheduled.state, TaskState.RETRY_SCHEDULED)
        self.assertEqual(scheduled.attempt_count, 1)
        self.assertIsNotNone(scheduled.next_attempt_at)
        self.assertEqual(transport.calls, 1)

        self.ledger.transition_task(
            task.task_id,
            from_state=TaskState.RETRY_SCHEDULED,
            to_state=TaskState.ENQUEUED,
        )
        self.ledger.create_outbox_event(task_id=task.task_id)
        self.dispatch_pending(1)
        second = worker.process_one()
        done = self.ledger.get_task(task.task_id)

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

        origin = self.ledger.create_task(
            idempotency_key="worker-replay-origin",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        self.ledger.claim_next_outbox_event()
        self.ledger.transition_task(
            origin.task_id,
            from_state=TaskState.CREATED,
            to_state=TaskState.DEAD_LETTER,
            error_json={"message": "previous failure"},
        )
        replay = self.ledger.replay_task(origin.task_id)
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        replay_after = self.ledger.get_task(replay.task_id)
        origin_after = self.ledger.get_task(origin.task_id)

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

        task = self.ledger.create_task(
            idempotency_key="cancelled-worker-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        cancelled = self.ledger.cancel_task(task.task_id)
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
        )
        self.dispatch_pending(1)

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

        release_store = ReleaseStore(self.db_path)
        release_store.set_health(
            manifest.release_id,
            health=ReleaseHealth.QUARANTINED,
            reason="test quarantine",
        )
        task = self.ledger.create_task(
            idempotency_key="quarantine-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            release_store=release_store,
        )
        self.dispatch_pending(1)

        result = worker.process_one()
        reloaded = self.ledger.get_task(task.task_id)

        self.assertEqual(result.state, TaskState.DEAD_LETTER)
        self.assertEqual(result.error_class, "PROTOCOL_RELEASE_BLOCKED")
        self.assertEqual(reloaded.error_json["error_class"], "PROTOCOL_RELEASE_BLOCKED")

    def test_worker_reclaims_stale_pending_delivery_after_crash(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        task = self.ledger.create_task(
            idempotency_key="crash-recovery-key",
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            request_json=request.public_dict(),
            plan_json=plan.public_dict(),
        )
        self.dispatch_pending(1)

        crashed_worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            owner="worker-crashed",
            redis_claim_min_idle_ms=0,
        )
        delivery = crashed_worker._read_next_delivery()
        self.assertIsNotNone(delivery)
        # Simulate a crash: the message is read (now pending in Redis) but the
        # worker dies before acquiring the Postgres lease or acking it.

        recovering_worker = self.make_worker(
            manifest=manifest,
            auth=WebSessionAuth("auth", "csrf", "bearer"),
            transport=FakeTransport(),
            raw_evidence_sink=FileRawEvidenceSink(Path(self.temp_dir.name) / "raw"),
            owner="worker-recovering",
            redis_claim_min_idle_ms=0,
        )
        result = recovering_worker.process_one()
        reloaded = self.ledger.get_task(task.task_id)

        self.assertTrue(result.processed)
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.state, TaskState.DONE)
        self.assertEqual(reloaded.state, TaskState.DONE)


if __name__ == "__main__":
    unittest.main()
