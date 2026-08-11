import json
from io import BytesIO
import tempfile
import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.capabilities import CapabilityPlanner, CapabilityRequest, SearchTweetsInput
from xingestion.migrations import MigrationRunner
from xingestion.releases import ReleaseStore
from xingestion.sessions import SessionHealth, SessionStore
from xingestion.tasks import SQLiteTaskLedger, TaskState
from xingestion.telemetry import ProtocolTelemetryStore
from xingestion.web import live_server
from xingestion.workers import WorkerResult
from xingestion.xprotocol.protocol import CapabilityId, ProtocolReleaseManifest


class FakeHandler(live_server.LiveAppHandler):
    def __init__(self):
        self.status = None
        self.payload = None
        self.headers_sent = {}
        self.wfile = BytesIO()

    def _json(self, payload, *, status=200):
        self.status = status
        self.payload = payload
        return payload

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.headers_sent[name.lower()] = value

    def end_headers(self):
        pass


class HeaderBackedHandler(FakeHandler):
    def __init__(self, headers):
        super().__init__()
        self.headers = headers


class StubOutboxWorker:
    def __init__(self, ledger, task_id):
        self.ledger = ledger
        self.task_id = task_id

    def process_one(self):
        event = self.ledger.claim_next_outbox_event()
        if event is None:
            return WorkerResult(processed=False)
        task = self.ledger.transition_task(
            self.task_id,
            from_state=TaskState.CREATED,
            to_state=TaskState.ENQUEUED,
        )
        return WorkerResult(processed=True, task_id=task.task_id, state=task.state)


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

    def test_operator_route_allows_missing_admin_header(self):
        live_server.STATE = SimpleNamespace(
            config=SimpleNamespace()
        )
        handler = HeaderBackedHandler(headers={})

        self.assertTrue(handler._require_admin())
        self.assertIsNone(handler.status)

    def test_operator_route_does_not_require_configured_token(self):
        live_server.STATE = SimpleNamespace(
            config=SimpleNamespace()
        )
        handler = HeaderBackedHandler(headers={})

        self.assertTrue(handler._require_admin())
        self.assertIsNone(handler.status)

    def test_operator_route_keeps_noop_guard_for_compatibility(self):
        live_server.STATE = SimpleNamespace(
            config=SimpleNamespace()
        )
        handler = HeaderBackedHandler(headers={})

        self.assertTrue(handler._require_admin())
        self.assertIsNone(handler.status)

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

    def test_import_sessions_route_loads_registry_without_reference_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry = root / "sessions.json"
            registry.write_text(
                json.dumps(
                    {
                        "sessions": [
                            {
                                "session_id": "session-a",
                                "account_label": "account-a",
                                "credential_ref": "file:session-a",
                                "network_context": "direct:iad",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            store = SessionStore(root / "tasks.sqlite3")
            live_server.STATE = SimpleNamespace(
                config=SimpleNamespace(
                    session_registry_path=registry,
                ),
                session_store=store,
            )
            handler = HeaderBackedHandler(headers={})

            payload = handler._import_sessions()

            raw = json.dumps(payload)
            self.assertEqual(handler.status, 201)
            self.assertEqual(payload["session_import"]["imported"], 1)
            self.assertEqual(store.get_session("session-a").network_context, "direct:iad")
            self.assertEqual(
                payload["session_import"]["sessions"][0]["network_policy"]["route"],
                "iad",
            )
            self.assertNotIn("file:session-a", raw)

    def test_network_health_dict_exposes_route_telemetry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = ProtocolTelemetryStore(Path(temp_dir) / "tasks.sqlite3")
            telemetry.record_attempt(
                task_id="task-1",
                capability_id="SEARCH_TWEETS",
                release_id="release-1",
                recipe_revision_id="recipe-1",
                state="SUCCESS",
                session_id="session-1",
                network_context="proxy:pool-a:iad",
            )
            telemetry.record_attempt(
                task_id="task-2",
                capability_id="SEARCH_TWEETS",
                release_id="release-1",
                recipe_revision_id="recipe-1",
                state="FAILURE",
                session_id="session-1",
                network_context="proxy:pool-a:iad",
                error_class="RATE_LIMITED",
            )
            live_server.STATE = SimpleNamespace(
                config=SimpleNamespace(worker_network_context="proxy:pool-a"),
                manifest=SimpleNamespace(release_id="release-1"),
                telemetry_store=telemetry,
            )

            payload = live_server._network_health_dict()

            self.assertEqual(payload["release_id"], "release-1")
            self.assertEqual(payload["worker_network_context"], "proxy:pool-a")
            self.assertEqual(payload["routes"][0]["network_context"], "proxy:pool-a:iad")
            self.assertEqual(payload["routes"][0]["successes"], 1)
            self.assertEqual(payload["routes"][0]["failures"], 1)
            self.assertEqual(payload["routes"][0]["failure_rate"], 0.5)
            self.assertEqual(payload["routes"][0]["errors_by_class"]["RATE_LIMITED"], 1)
            self.assertIsNone(payload["routes"][0]["recommendation"])

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

    def test_outbox_route_lists_pending_events(self):
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
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="outbox-route",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            live_server.STATE = SimpleNamespace(ledger=ledger)
            handler = FakeHandler()
            handler.path = "/api/outbox"

            payload = handler.do_GET()

            self.assertEqual(handler.status, 200)
            self.assertEqual(payload["stats"]["unpublished_events"], 1)
            self.assertEqual(payload["events"][0]["task_id"], task.task_id)

    def test_protocol_validation_route_returns_fixture_report(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "raw"
            raw_dir.mkdir()
            live_server.STATE = SimpleNamespace(
                config=SimpleNamespace(raw_evidence_dir=raw_dir),
                manifest=manifest,
            )
            handler = FakeHandler()
            handler.path = "/api/protocol-validation"

            payload = handler.do_GET()

            self.assertEqual(handler.status, 200)
            self.assertTrue(payload["validation"]["ok"])
            self.assertGreaterEqual(payload["validation"]["checked_sources"], 1)
            self.assertEqual(payload["validation"]["results"][0]["source_type"], "fixture")

    def test_protocol_validation_run_route_saves_report(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            live_server.STATE = SimpleNamespace(
                config=SimpleNamespace(
                    data_dir=root / "data",
                    raw_evidence_dir=raw_dir,
                ),
                manifest=manifest,
            )
            handler = HeaderBackedHandler(headers={})

            payload = handler._run_protocol_validation()

            self.assertEqual(handler.status, 201)
            self.assertTrue(payload["validation"]["ok"])
            self.assertTrue(Path(payload["saved_path"]).exists())

            handler.path = "/api/protocol-validation/reports"
            listing = handler.do_GET()

            self.assertEqual(handler.status, 200)
            self.assertEqual(len(listing["reports"]), 1)

    def test_outbox_process_route_requires_worker(self):
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
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="outbox-process-route",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            live_server.STATE = SimpleNamespace(
                config=SimpleNamespace(),
                ledger=ledger,
                worker=StubOutboxWorker(ledger, task.task_id),
            )
            handler = HeaderBackedHandler(headers={})

            payload = handler._process_outbox({"limit": 5})

            self.assertEqual(handler.status, 200)
            self.assertEqual(payload["outbox_process"]["processed_events"], 1)
            self.assertEqual(
                payload["outbox_process"]["after"]["unpublished_events"],
                0,
            )

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
                    retention_days=30,
                ),
                manifest=manifest,
            )
            handler = FakeHandler()

            payload = handler._export_failed_task(failed.task_id)

            self.assertEqual(handler.status, 201)
            self.assertEqual(payload["export"]["task_id"], failed.task_id)
            self.assertEqual(payload["export"]["support_summary"]["severity"], "CRITICAL")
            self.assertTrue(Path(payload["export"]["path"]).exists())

            handler.path = "/api/support-exports"
            listing = handler.do_GET()

            self.assertEqual(handler.status, 200)
            self.assertEqual(listing["exports"][0]["task_id"], failed.task_id)
            self.assertEqual(listing["exports"][0]["severity"], "CRITICAL")
            self.assertIn("support_exports", listing["export_dir"])

            name = Path(payload["export"]["path"]).name
            handler.path = f"/api/support-exports/{name}"
            detail = handler.do_GET()

            self.assertEqual(handler.status, 200)
            self.assertEqual(detail["export"]["summary"]["name"], name)
            self.assertEqual(detail["export"]["package"]["task_id"], failed.task_id)

            handler._download_support_export(name)

            self.assertEqual(handler.status, 200)
            self.assertEqual(handler.headers_sent["content-type"], "application/json; charset=utf-8")
            self.assertEqual(
                handler.headers_sent["content-disposition"],
                f'attachment; filename="{name}"',
            )
            self.assertEqual(
                handler.wfile.getvalue(),
                Path(payload["export"]["path"]).read_bytes(),
            )

            handler.path = "/api/support-exports/..%5Csecrets.json"
            handler.do_GET()

            self.assertEqual(handler.status, 400)

    def test_startup_route_returns_preflight_checks(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "tasks.sqlite3"
            runner = MigrationRunner(
                db_path,
                ROOT / "src" / "xingestion" / "migrations" / "sql",
            )
            runner.apply()
            SessionStore(db_path).upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )
            live_server.STATE = SimpleNamespace(
                config=SimpleNamespace(
                    data_dir=root / "data",
                    sqlite_path=db_path,
                    raw_evidence_dir=root / "data" / "raw_evidence",
                    default_credential_ref="env:X_AUTH_TOKEN,X_CT0,X_BEARER",
                    secret_provider="env",
                    secret_dir=root / "data" / "secrets",
                ),
                migration_runner=runner,
                manifest=manifest,
                auth=SimpleNamespace(missing_fields=lambda: []),
            )
            handler = FakeHandler()
            handler.path = "/api/startup"

            payload = handler.do_GET()

            self.assertEqual(handler.status, 200)
            self.assertTrue(payload["ok"])
            checks = {check["name"]: check["status"] for check in payload["checks"]}
            self.assertEqual(checks["startup_directories"], "PASS")
            self.assertEqual(checks["migrations"], "PASS")

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
