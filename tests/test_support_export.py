import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.capabilities import CapabilityPlanner, CapabilityRequest, SearchTweetsInput
from xingestion.config import AppConfig
from xingestion.releases import ReleaseStore
from xingestion.sessions import SessionStore
from xingestion.support_export import (
    apply_support_export_retention,
    build_failed_task_export,
    list_support_exports,
    read_support_export,
    support_export_file,
    write_failed_task_export,
)
from xingestion.tasks import SQLiteTaskLedger, TaskState
from xingestion.telemetry import ProtocolTelemetryStore
from xrev.protocol import CapabilityId, ProtocolReleaseManifest


def load_manifest():
    return ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )


class SupportExportTests(unittest.TestCase):
    def test_write_failed_task_support_export(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = _config(root)
            config.data_dir.mkdir(parents=True, exist_ok=True)
            ledger = SQLiteTaskLedger(config.sqlite_path)
            sessions = SessionStore(config.sqlite_path)
            releases = ReleaseStore(config.sqlite_path)
            telemetry = ProtocolTelemetryStore(config.sqlite_path)
            sessions.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )
            failed = _failed_task(ledger, manifest)
            telemetry.record_attempt(
                task_id=failed.task_id,
                capability_id=failed.capability_id.value,
                release_id=manifest.release_id,
                recipe_revision_id=str(failed.plan_json["recipe_revision_id"]),
                state="FAILURE",
                session_id="session-1",
                error_class="OPERATION_NOT_FOUND",
                duration_ms=12,
            )

            result = write_failed_task_export(
                task_id=failed.task_id,
                config=config,
                manifest=manifest,
                output_path=root / "support.json",
            )

            saved = json.loads(result.path.read_text(encoding="utf-8"))
            raw = json.dumps(saved)
            self.assertEqual(saved["package_type"], "FAILED_TASK_SUPPORT_EXPORT")
            self.assertEqual(saved["task_id"], failed.task_id)
            self.assertEqual(saved["runtime_error"]["severity"], "CRITICAL")
            self.assertEqual(saved["support_summary"]["scope"], "PROTOCOL")
            self.assertEqual(saved["support_summary"]["telemetry_attempts"], 1)
            self.assertFalse(saved["redaction"]["raw_x_secrets_included"])
            self.assertNotIn("credential_ref", raw)
            self.assertNotIn("secret:x/session-1", raw)

            direct = build_failed_task_export(
                task_id=failed.task_id,
                ledger=ledger,
                manifest=manifest,
                release_store=releases,
                session_store=sessions,
                telemetry_store=telemetry,
            )
            self.assertEqual(direct["support_summary"]["error_class"], "OPERATION_NOT_FOUND")

    def test_export_rejects_task_without_error(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            ledger = SQLiteTaskLedger(db_path)
            request = CapabilityRequest(
                capability_id=CapabilityId.SEARCH_TWEETS,
                contract_version=1,
                payload=SearchTweetsInput(query="india", page_size=20),
            )
            task = ledger.create_task(
                idempotency_key="not-failed",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=CapabilityPlanner(manifest).plan(request).public_dict(),
            )

            with self.assertRaisesRegex(ValueError, "no error_json"):
                build_failed_task_export(
                    task_id=task.task_id,
                    ledger=ledger,
                    manifest=manifest,
                    release_store=ReleaseStore(db_path),
                    session_store=SessionStore(db_path),
                    telemetry_store=ProtocolTelemetryStore(db_path),
                )

    def test_list_and_prune_support_exports(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = _config(root)
            config.data_dir.mkdir(parents=True, exist_ok=True)
            ledger = SQLiteTaskLedger(config.sqlite_path)
            failed = _failed_task(ledger, manifest)
            export_dir = config.data_dir / "support_exports"
            old_path = export_dir / "failed-task-old.json"
            new_path = export_dir / "failed-task-new.json"
            write_failed_task_export(
                task_id=failed.task_id,
                config=config,
                manifest=manifest,
                output_path=old_path,
            )
            write_failed_task_export(
                task_id=failed.task_id,
                config=config,
                manifest=manifest,
                output_path=new_path,
            )
            old_mtime = (datetime.now(UTC) - timedelta(days=3)).timestamp()
            os.utime(old_path, (old_mtime, old_mtime))

            summaries = list_support_exports(config)

            self.assertEqual({item.name for item in summaries}, {"failed-task-old.json", "failed-task-new.json"})
            self.assertTrue(all(item.redacted for item in summaries))
            dry_run = apply_support_export_retention(config, days=1, dry_run=True)
            self.assertEqual(dry_run.matched_exports, 1)
            self.assertEqual(dry_run.deleted_exports, 0)
            self.assertTrue(old_path.exists())

            result = apply_support_export_retention(config, days=1, dry_run=False)

            self.assertEqual(result.matched_exports, 1)
            self.assertEqual(result.deleted_exports, 1)
            self.assertFalse(old_path.exists())
            self.assertTrue(new_path.exists())

    def test_read_support_export_rejects_unsafe_names(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = _config(root)
            config.data_dir.mkdir(parents=True, exist_ok=True)
            ledger = SQLiteTaskLedger(config.sqlite_path)
            failed = _failed_task(ledger, manifest)
            result = write_failed_task_export(
                task_id=failed.task_id,
                config=config,
                manifest=manifest,
                output_path=config.data_dir / "support_exports" / "failed-task-safe.json",
            )

            read = read_support_export(config, result.path.name)

            self.assertEqual(read["summary"]["name"], "failed-task-safe.json")
            self.assertEqual(read["package"]["task_id"], failed.task_id)
            self.assertEqual(support_export_file(config, result.path.name), result.path)
            with self.assertRaisesRegex(ValueError, "file name"):
                read_support_export(config, "..\\secrets.json")
            with self.assertRaisesRegex(ValueError, "failed-task"):
                read_support_export(config, "health-report.json")


def _failed_task(ledger: SQLiteTaskLedger, manifest: ProtocolReleaseManifest):
    request = CapabilityRequest(
        capability_id=CapabilityId.SEARCH_TWEETS,
        contract_version=1,
        payload=SearchTweetsInput(query="india", page_size=20),
    )
    task = ledger.create_task(
        idempotency_key="failed-export",
        capability_id=request.capability_id,
        contract_version=request.contract_version,
        request_json=request.public_dict(),
        plan_json=CapabilityPlanner(manifest).plan(request).public_dict(),
    )
    return ledger.transition_task(
        task.task_id,
        from_state=TaskState.CREATED,
        to_state=TaskState.DEAD_LETTER,
        error_json={
            "error_class": "OPERATION_NOT_FOUND",
            "message": "X returned HTTP 404 for the pinned operation",
        },
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
        secret_provider="env",
        secret_dir=root / "data" / "secrets",
        require_migrations=True,
        max_active_tasks_per_capability=100,
    )


if __name__ == "__main__":
    unittest.main()
