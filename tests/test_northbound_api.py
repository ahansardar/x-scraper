import json
import tempfile
import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.capabilities import CapabilityPlanner, CapabilityRequest, SearchTweetsInput
from xingestion.releases import ReleaseStore
from xingestion.sessions import SessionHealth, SessionStore
from xingestion.tasks import SQLiteTaskLedger, TaskState
from xingestion.telemetry import ProtocolTelemetryStore
from xingestion.web import live_server
from xrev.protocol import CapabilityId, ProtocolReleaseManifest


class FakeHandler(live_server.LiveAppHandler):
    def __init__(self):
        self.status = None
        self.payload = None

    def _json(self, payload, *, status=200):
        self.status = status
        self.payload = payload
        return payload


class HeaderBackedHandler(FakeHandler):
    def __init__(self, headers):
        super().__init__()
        self.headers = headers


class NorthboundApiTests(unittest.TestCase):
    def test_generic_capability_task_submission_queues_task(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            live_server.STATE = SimpleNamespace(
                config=SimpleNamespace(max_active_tasks_per_capability=100),
                planner=CapabilityPlanner(manifest),
                ledger=SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3"),
            )
            handler = FakeHandler()

            payload = handler._create_capability_task(
                {
                    "capability_id": "SEARCH_TWEETS",
                    "contract_version": 1,
                    "payload": {
                        "query": "india lang:en",
                        "product": "Top",
                        "page_size": 20,
                        "max_pages": 2,
                    },
                    "idempotency_key": "northbound-1",
                }
            )

            self.assertEqual(handler.status, 202)
            self.assertEqual(payload["task"]["capability_id"], "SEARCH_TWEETS")
            self.assertEqual(payload["status_url"], f"/api/tasks/{payload['task']['task_id']}")
            task = live_server.STATE.ledger.get_task(payload["task"]["task_id"])
            self.assertEqual(task.request_json["payload"]["max_pages"], 2)

    def test_generic_capability_respects_backpressure_limit(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            live_server.STATE = SimpleNamespace(
                config=SimpleNamespace(max_active_tasks_per_capability=1),
                planner=CapabilityPlanner(manifest),
                ledger=ledger,
            )
            handler = FakeHandler()
            payload = {
                "capability_id": "SEARCH_TWEETS",
                "contract_version": 1,
                "payload": {"query": "india", "page_size": 20},
            }

            handler._create_capability_task({**payload, "idempotency_key": "bp-1"})
            rejected = handler._create_capability_task({**payload, "idempotency_key": "bp-2"})

            self.assertEqual(handler.status, 429)
            self.assertEqual(rejected["message"], "Backpressure limit reached")
            self.assertEqual(rejected["active_tasks"], 1)

    def test_generic_capability_rejects_unknown_capability(self):
        handler = FakeHandler()

        payload = handler._create_capability_task(
            {
                "capability_id": "UNKNOWN",
                "contract_version": 1,
                "payload": {},
            }
        )

        self.assertEqual(handler.status, 400)
        self.assertIn("Unsupported capability", payload["message"])

    def test_operator_route_requires_configured_admin_token(self):
        live_server.STATE = SimpleNamespace(
            config=SimpleNamespace(admin_token="expected-token")
        )
        handler = HeaderBackedHandler(headers={})

        result = handler._require_admin()

        self.assertFalse(result)
        self.assertEqual(handler.status, 401)
        self.assertIn("Admin token required", handler.payload["message"])

    def test_operator_route_accepts_matching_admin_token(self):
        live_server.STATE = SimpleNamespace(
            config=SimpleNamespace(admin_token="expected-token")
        )
        handler = HeaderBackedHandler(headers={"x-admin-token": "expected-token"})

        self.assertTrue(handler._require_admin())

    def test_operator_route_rejects_when_admin_token_unconfigured(self):
        live_server.STATE = SimpleNamespace(
            config=SimpleNamespace(admin_token="")
        )
        handler = HeaderBackedHandler(headers={"x-admin-token": "anything"})

        result = handler._require_admin()

        self.assertFalse(result)
        self.assertEqual(handler.status, 503)
        self.assertIn("not configured", handler.payload["message"])

    def test_api_miss_returns_json_not_html(self):
        handler = FakeHandler()

        payload = handler._api_not_found("/api/missing")

        self.assertEqual(handler.status, 404)
        self.assertEqual(payload["message"], "API route not found: /api/missing")

    def test_migration_status_dict_is_public_safe(self):
        status = SimpleNamespace(
            current=False,
            available_versions=("001", "002"),
            applied_versions=("001",),
            pending_versions=("002",),
        )

        payload = live_server._migration_status_dict(status)

        self.assertFalse(payload["current"])
        self.assertEqual(payload["pending_versions"], ["002"])

    def test_restore_session_marks_session_healthy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "tasks.sqlite3")
            store.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
                health=SessionHealth.AUTH_EXPIRED,
            )
            live_server.STATE = SimpleNamespace(session_store=store)
            handler = FakeHandler()

            payload = handler._restore_session("session-1")

            self.assertEqual(handler.status, 200)
            self.assertEqual(payload["session"]["health"], "HEALTHY")
            self.assertIsNone(payload["session"]["cooldown_until"])
            self.assertEqual(store.get_session("session-1").health, SessionHealth.HEALTHY)

    def test_disable_session_marks_session_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "tasks.sqlite3")
            store.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )
            live_server.STATE = SimpleNamespace(session_store=store)
            handler = FakeHandler()

            payload = handler._disable_session("session-1")
            acquired = store.acquire_session(owner="worker-a", lease_seconds=60)

            self.assertEqual(handler.status, 200)
            self.assertEqual(payload["session"]["health"], "DISABLED")
            self.assertIsNone(acquired)

    def test_investigate_task_returns_package(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
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
            sessions = SessionStore(db_path)
            sessions.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )
            task = ledger.create_task(
                idempotency_key="investigate-route",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            failed = ledger.transition_task(
                task.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.DEAD_LETTER,
                error_json={"error_class": "OPERATION_NOT_FOUND"},
            )
            telemetry.record_attempt(
                task_id=failed.task_id,
                capability_id=failed.capability_id.value,
                release_id=manifest.release_id,
                recipe_revision_id=str(failed.plan_json["recipe_revision_id"]),
                state="FAILURE",
                session_id="session-1",
                error_class="OPERATION_NOT_FOUND",
            )
            live_server.STATE = SimpleNamespace(
                ledger=ledger,
                manifest=manifest,
                release_store=ReleaseStore(db_path),
                session_store=sessions,
                telemetry_store=telemetry,
            )
            handler = FakeHandler()

            payload = handler._investigate_task(failed.task_id)

            self.assertEqual(handler.status, 200)
            self.assertEqual(
                payload["investigation"]["package_type"],
                "PROTOCOL_DRIFT_INVESTIGATION",
            )
            self.assertEqual(payload["investigation"]["task"]["task_id"], failed.task_id)

    def test_task_actions_route_returns_operator_actions(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            ledger = SQLiteTaskLedger(db_path)
            task = ledger.create_task(
                idempotency_key="task-actions-route",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            failed = ledger.transition_task(
                task.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.DEAD_LETTER,
                error_json={"error_class": "OPERATION_NOT_FOUND"},
            )
            live_server.STATE = SimpleNamespace(
                config=SimpleNamespace(sqlite_path=db_path),
            )
            handler = FakeHandler()
            handler.path = "/api/task-actions"

            payload = handler.do_GET()

            self.assertEqual(handler.status, 200)
            self.assertEqual(payload["actions"][0]["task_id"], failed.task_id)
            self.assertEqual(payload["actions"][0]["severity"], "CRITICAL")
            self.assertTrue(payload["actions"][0]["replayable"])

    def test_export_failed_task_writes_support_package(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "tasks.sqlite3"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            ledger = SQLiteTaskLedger(db_path)
            sessions = SessionStore(db_path)
            sessions.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )
            task = ledger.create_task(
                idempotency_key="export-route",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            failed = ledger.transition_task(
                task.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.DEAD_LETTER,
                error_json={"error_class": "OPERATION_NOT_FOUND"},
            )
            live_server.STATE = SimpleNamespace(
                config=SimpleNamespace(
                    data_dir=root / "data",
                    sqlite_path=db_path,
                ),
                manifest=manifest,
            )
            handler = FakeHandler()

            payload = handler._export_failed_task(failed.task_id)

            self.assertEqual(handler.status, 201)
            self.assertEqual(payload["export"]["task_id"], failed.task_id)
            self.assertEqual(payload["export"]["support_summary"]["severity"], "CRITICAL")
            self.assertTrue(Path(payload["export"]["path"]).exists())

    def test_release_risk_dict_returns_recommendation(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            telemetry = ProtocolTelemetryStore(db_path)
            for index in range(3):
                telemetry.record_attempt(
                    task_id=f"task-{index}",
                    capability_id="SEARCH_TWEETS",
                    release_id=manifest.release_id,
                    recipe_revision_id="recipe-1",
                    state="FAILURE",
                    session_id=f"session-{index}",
                    error_class="OPERATION_NOT_FOUND",
                )
            live_server.STATE = SimpleNamespace(
                manifest=manifest,
                release_store=ReleaseStore(db_path),
                telemetry_store=telemetry,
            )

            risk = live_server._release_risk_dict()

            self.assertEqual(risk["action"], "QUARANTINE_RECOMMENDED")
            self.assertEqual(risk["severity"], "HIGH")


if __name__ == "__main__":
    unittest.main()
