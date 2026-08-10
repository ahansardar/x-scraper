import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.capabilities import CapabilityPlanner, CapabilityRequest, SearchTweetsInput
from xingestion.investigation import build_protocol_drift_package
from xingestion.releases import ReleaseStore
from xingestion.sessions import SessionHealth, SessionStore
from xingestion.tasks import SQLiteTaskLedger, TaskState
from xingestion.telemetry import ProtocolTelemetryStore
from xrev.protocol import CapabilityId, ProtocolReleaseManifest


def load_manifest():
    return ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )


class InvestigationTests(unittest.TestCase):
    def test_builds_safe_protocol_drift_package_for_failed_task(self):
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
            releases = ReleaseStore(db_path)
            sessions = SessionStore(db_path)
            telemetry = ProtocolTelemetryStore(db_path)
            sessions.upsert_session(
                session_id="session-1",
                account_label="account",
                credential_ref="secret:x/session-1",
            )
            sessions.update_health(
                "session-1",
                health=SessionHealth.DEGRADED,
                reason="operation failed",
            )
            sessions.record_attempt_started("session-1")
            sessions.record_attempt_failure(
                "session-1",
                error_class="OPERATION_NOT_FOUND",
                error_message="X returned HTTP 404 for the pinned operation",
            )
            task = ledger.create_task(
                idempotency_key="investigation-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            failed = ledger.transition_task(
                task.task_id,
                from_state=TaskState.CREATED,
                to_state=TaskState.DEAD_LETTER,
                error_json={
                    "error_class": "OPERATION_NOT_FOUND",
                    "message": "X returned HTTP 404 for the pinned operation",
                },
            )
            telemetry.record_attempt(
                task_id=failed.task_id,
                capability_id=failed.capability_id.value,
                release_id=manifest.release_id,
                recipe_revision_id=str(failed.plan_json["recipe_revision_id"]),
                state="FAILURE",
                session_id="session-1",
                error_class="OPERATION_NOT_FOUND",
                duration_ms=42,
            )

            package = build_protocol_drift_package(
                task_id=failed.task_id,
                ledger=ledger,
                manifest=manifest,
                release_store=releases,
                session_store=sessions,
                telemetry_store=telemetry,
            )

            self.assertEqual(package["package_type"], "PROTOCOL_DRIFT_INVESTIGATION")
            self.assertEqual(package["task"]["task_id"], failed.task_id)
            self.assertEqual(package["diagnosis"]["primary_error_class"], "OPERATION_NOT_FOUND")
            self.assertIn("Pinned X GraphQL operation", package["diagnosis"]["hints"][0])
            self.assertEqual(package["release"]["manifest_release_id"], manifest.release_id)
            self.assertEqual(package["recipe"]["operation"]["operation_name"], "SearchTimeline")
            self.assertEqual(package["session"]["session_id"], "session-1")
            self.assertEqual(package["session"]["last_error_class"], "OPERATION_NOT_FOUND")
            self.assertEqual(len(package["telemetry_attempts"]), 1)
            self.assertIsNone(package["raw_evidence"])
            self.assertNotIn("credential_ref", package["session"])

    def test_missing_task_is_rejected(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            with self.assertRaisesRegex(ValueError, "not found"):
                build_protocol_drift_package(
                    task_id="task-missing",
                    ledger=SQLiteTaskLedger(db_path),
                    manifest=manifest,
                    release_store=ReleaseStore(db_path),
                    session_store=SessionStore(db_path),
                    telemetry_store=ProtocolTelemetryStore(db_path),
                )


if __name__ == "__main__":
    unittest.main()
