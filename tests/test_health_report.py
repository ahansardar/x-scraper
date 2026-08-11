import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.config import AppConfig
from xingestion.health_report import build_health_report, write_health_report
from xingestion.migrations import MigrationRunner
from xingestion.sessions import SessionStore
from xingestion.tasks import SQLiteTaskLedger, TaskState
from xrev.protocol import CapabilityId, ProtocolReleaseManifest
from xrev.runtime import WebSessionAuth


def load_manifest():
    return ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )


class HealthReportTests(unittest.TestCase):
    def test_health_report_writes_safe_operator_snapshot(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = _config(root)
            runner = _runner(config)
            runner.apply()
            SessionStore(config.sqlite_path).upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
                network_context="direct",
            )
            ledger = SQLiteTaskLedger(config.sqlite_path)
            ledger.create_task(
                idempotency_key="report-task",
                capability_id=CapabilityId.SEARCH_TWEETS,
                contract_version=1,
                request_json={"capability_id": "SEARCH_TWEETS"},
                plan_json={"recipe_revision_id": "recipe-test"},
            )
            failed = ledger.create_task(
                idempotency_key="failed-task",
                capability_id=CapabilityId.SEARCH_TWEETS,
                contract_version=1,
                request_json={"capability_id": "SEARCH_TWEETS"},
                plan_json={"recipe_revision_id": "recipe-test"},
            )
            ledger.transition_task(
                failed.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.DEAD_LETTER,
                error_json={
                    "error_class": "OPERATION_NOT_FOUND",
                    "message": "X returned HTTP 404 for the pinned operation",
                },
            )

            result = write_health_report(
                config=config,
                migration_runner=runner,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
                output_path=root / "report.json",
            )

            saved = json.loads(result.path.read_text(encoding="utf-8"))
            raw = json.dumps(saved)
            self.assertTrue(result.ok)
            self.assertEqual(saved["report_type"], "XINGESTION_HEALTH_REPORT")
            self.assertEqual(saved["tasks"]["state_counts"]["CREATED"], 1)
            self.assertEqual(saved["runtime_errors"]["by_class"]["OPERATION_NOT_FOUND"], 1)
            self.assertEqual(saved["runtime_errors"]["by_severity"]["CRITICAL"], 1)
            self.assertEqual(
                saved["runtime_errors"]["recent"][0]["runtime_error"]["operator_action"],
                "investigate_protocol_release_and_consider_quarantine",
            )
            self.assertEqual(saved["sessions"]["total"], 1)
            self.assertIn("release_risk", saved)
            self.assertIn("storage", saved)
            self.assertNotIn("credential_ref", raw)
            self.assertNotIn("lease_token", raw)
            self.assertNotIn("secret:x/session-1", raw)

    def test_health_report_marks_preflight_failures_without_crashing(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = _config(root)

            report = build_health_report(
                config=config,
                migration_runner=_runner(config),
                manifest=manifest,
                auth=WebSessionAuth("", "", ""),
            )

            statuses = {check["name"]: check["status"] for check in report["preflight"]}
            self.assertFalse(report["ok"])
            self.assertEqual(statuses["migrations"], "FAIL")
            self.assertEqual(statuses["sessions"], "FAIL")
            self.assertIn("pending_versions", report["migrations"])


def _runner(config: AppConfig) -> MigrationRunner:
    return MigrationRunner(
        config.sqlite_path,
        ROOT / "src" / "xingestion" / "migrations" / "sql",
    )


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
