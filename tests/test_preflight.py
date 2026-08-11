import tempfile
import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.capabilities import CapabilityPlanner, CapabilityRequest, SearchTweetsInput
from xingestion.config import AppConfig
from xingestion.migrations import MigrationRunner
from xingestion.preflight import DeploymentPreflight
from xingestion.sessions import SessionHealth, SessionStore
from xingestion.tasks import SQLiteTaskLedger, TaskState
from xingestion.telemetry import ProtocolTelemetryStore
from xrev.protocol import CapabilityId, ProtocolReleaseManifest
from xrev.runtime import WebSessionAuth


def load_manifest():
    return ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )


class FakeApiPreflight(DeploymentPreflight):
    def __init__(self, responses, **kwargs):
        super().__init__(base_url="http://test", **kwargs)
        self.responses = responses

    def _get(self, path):
        if path not in self.responses:
            raise RuntimeError(f"missing fake response for {path}")
        return self.responses[path]


class PreflightTests(unittest.TestCase):
    def test_preflight_passes_ready_local_state_without_api(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = _config(root)
            runner = MigrationRunner(
                config.sqlite_path,
                ROOT / "src" / "xingestion" / "migrations" / "sql",
            )
            runner.apply()
            sessions = SessionStore(config.sqlite_path)
            sessions.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )

            result = DeploymentPreflight(
                config=config,
                migration_runner=runner,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
            ).run()

            statuses = {check.name: check.status for check in result.checks}
            self.assertTrue(result.ok)
            self.assertEqual(statuses["migrations"], "PASS")
            self.assertEqual(statuses["storage"], "PASS")
            self.assertEqual(statuses["startup_directories"], "PASS")
            self.assertEqual(statuses["auth"], "PASS")
            self.assertEqual(statuses["sessions"], "PASS")
            self.assertEqual(statuses["api"], "WARN")
            self.assertTrue((config.data_dir / "reports").exists())
            self.assertTrue((config.data_dir / "support_exports").exists())
            self.assertTrue((config.data_dir / "logs").exists())

    def test_preflight_fails_pending_migrations_and_no_sessions(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = _config(root)
            runner = MigrationRunner(
                config.sqlite_path,
                ROOT / "src" / "xingestion" / "migrations" / "sql",
            )

            result = DeploymentPreflight(
                config=config,
                migration_runner=runner,
                manifest=manifest,
                auth=WebSessionAuth("", "", ""),
            ).run()

            statuses = {check.name: check.status for check in result.checks}
            self.assertFalse(result.ok)
            self.assertEqual(statuses["migrations"], "FAIL")
            self.assertEqual(statuses["auth"], "WARN")
            self.assertEqual(statuses["sessions"], "FAIL")
            self.assertEqual(statuses["startup_directories"], "PASS")

    def test_preflight_fails_release_risk_quarantine_recommendation(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = _config(root)
            runner = MigrationRunner(
                config.sqlite_path,
                ROOT / "src" / "xingestion" / "migrations" / "sql",
            )
            runner.apply()
            sessions = SessionStore(config.sqlite_path)
            sessions.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )
            ledger = SQLiteTaskLedger(config.sqlite_path)
            telemetry = ProtocolTelemetryStore(config.sqlite_path)
            for index in range(3):
                task = ledger.create_task(
                    idempotency_key=f"risk-{index}",
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
                    session_id=f"session-{index}",
                    error_class="OPERATION_NOT_FOUND",
                )

            result = DeploymentPreflight(
                config=config,
                migration_runner=runner,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
            ).run()

            release_check = next(check for check in result.checks if check.name == "release")
            self.assertFalse(result.ok)
            self.assertEqual(release_check.status, "FAIL")
            self.assertIn("QUARANTINE_RECOMMENDED", release_check.message)

    def test_api_shape_probe_requires_expected_keys(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = _config(root)
            runner = MigrationRunner(
                config.sqlite_path,
                ROOT / "src" / "xingestion" / "migrations" / "sql",
            )
            runner.apply()
            SessionStore(config.sqlite_path).upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )
            responses = {
                "/api/health": {"release_id": "release-1", "auth_ready": True},
                "/api/storage": {"sqlite_path": "x", "raw_evidence_dir": "raw"},
                "/api/metrics": {"tasks": {}, "release_risk": {}, "sessions": {}},
                "/api/migrations": {"migrations": {}},
                "/api/sessions": {"sessions": []},
                "/api/releases/current": {"release": {}},
                "/api/releases/current/risk": {"risk": {}},
            }

            result = FakeApiPreflight(
                responses,
                config=config,
                migration_runner=runner,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
            ).run()

            statuses = {check.name: check.status for check in result.checks}
            self.assertTrue(result.ok)
            self.assertEqual(statuses["api"], "PASS")


def _config(root: Path) -> AppConfig:
    return AppConfig(
        root=root,
        data_dir=root / "data",
        sqlite_path=root / "data" / "tasks.sqlite3",
        raw_evidence_dir=root / "data" / "raw_evidence",
        host="127.0.0.1",
        port=8000,
        retention_days=30,
        default_session_id="session-1",
        default_account_label="local",
        default_credential_ref="env:X_AUTH_TOKEN,X_CT0,X_BEARER",
        default_network_context="direct",
        admin_token="token",
        require_migrations=True,
        max_active_tasks_per_capability=100,
    )


if __name__ == "__main__":
    unittest.main()
