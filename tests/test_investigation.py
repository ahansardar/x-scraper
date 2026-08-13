import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from postgres_fixture import make_postgres_ledger

from xingestion.capabilities import CapabilityPlanner, CapabilityRequest, SearchTweetsInput
from xingestion.investigation import (
    build_network_route_recommendations,
    build_protocol_drift_package,
    build_protocol_drift_report,
    build_release_risk_recommendation,
)
from xingestion.releases import RecipeValidationStore, ReleaseStore, record_recipe_validation_results
from xingestion.sessions import SessionHealth, SessionStore
from xingestion.tasks import TaskState
from xingestion.telemetry import ProtocolTelemetryStore
from xingestion.xprotocol.protocol import CapabilityId, ProtocolReleaseManifest


def load_manifest():
    return ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.ledger = make_postgres_ledger()
        except Exception as exc:  # pragma: no cover - environment dependent
            self.skipTest(f"Postgres unavailable: {exc}")

    def tearDown(self):
        self.ledger.pool.close()

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
            ledger = self.ledger
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
                    ledger=self.ledger,
                    manifest=manifest,
                    release_store=ReleaseStore(db_path),
                    session_store=SessionStore(db_path),
                    telemetry_store=ProtocolTelemetryStore(db_path),
                )

    def test_release_risk_recommends_quarantine_for_repeated_operation_failures(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            releases = ReleaseStore(db_path)
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

            risk = build_release_risk_recommendation(
                manifest=manifest,
                release_store=releases,
                telemetry_store=telemetry,
            )

            self.assertEqual(risk["action"], "QUARANTINE_RECOMMENDED")
            self.assertEqual(risk["severity"], "HIGH")
            self.assertEqual(risk["signals"][0]["error_class"], "OPERATION_NOT_FOUND")
            self.assertEqual(risk["signals"][0]["distinct_sessions"], 3)

    def test_release_risk_treats_session_errors_as_no_release_action(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            releases = ReleaseStore(db_path)
            telemetry = ProtocolTelemetryStore(db_path)
            for index in range(5):
                telemetry.record_attempt(
                    task_id=f"task-{index}",
                    capability_id="SEARCH_TWEETS",
                    release_id=manifest.release_id,
                    recipe_revision_id="recipe-1",
                    state="FAILURE",
                    session_id="session-1",
                    error_class="RATE_LIMITED",
                )

            risk = build_release_risk_recommendation(
                manifest=manifest,
                release_store=releases,
                telemetry_store=telemetry,
            )

            self.assertEqual(risk["action"], "NO_ACTION")
            self.assertEqual(risk["severity"], "LOW")

    def test_release_risk_recommends_network_remediation_for_bad_route(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            releases = ReleaseStore(db_path)
            telemetry = ProtocolTelemetryStore(db_path)
            for index in range(6):
                telemetry.record_attempt(
                    task_id=f"task-{index}",
                    capability_id="SEARCH_TWEETS",
                    release_id=manifest.release_id,
                    recipe_revision_id="recipe-1",
                    state="FAILURE",
                    session_id="session-1",
                    network_context="proxy:pool-a:iad",
                    error_class="RATE_LIMITED",
                )

            risk = build_release_risk_recommendation(
                manifest=manifest,
                release_store=releases,
                telemetry_store=telemetry,
            )

            self.assertEqual(risk["action"], "NETWORK_REMEDIATION_RECOMMENDED")
            self.assertEqual(risk["severity"], "HIGH")
            self.assertEqual(risk["operator_action"], "pause_or_rotate_unhealthy_network_routes_before_changing_release")
            self.assertEqual(risk["network_routes"][0]["network_context"], "proxy:pool-a:iad")
            self.assertEqual(risk["network_routes"][0]["operator_action"], "pause_route_wait_for_cooldown_or_add_healthy_session_capacity")

    def test_network_route_recommendations_ignore_other_releases(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = ProtocolTelemetryStore(Path(temp_dir) / "tasks.sqlite3")
            for index in range(6):
                telemetry.record_attempt(
                    task_id=f"task-{index}",
                    capability_id="SEARCH_TWEETS",
                    release_id="old-release",
                    recipe_revision_id="recipe-1",
                    state="FAILURE",
                    session_id="session-1",
                    network_context="proxy:pool-a:iad",
                    error_class="RATE_LIMITED",
                )

            recommendations = build_network_route_recommendations(
                telemetry_store=telemetry,
                release_id=manifest.release_id,
            )

            self.assertEqual(recommendations, [])

    def test_drift_report_flags_hard_signal_error_in_recent_window(self):
        manifest = load_manifest()
        recipe_revision_id = manifest.bindings[0].recipe.revision_id
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            releases = ReleaseStore(db_path)
            telemetry = ProtocolTelemetryStore(db_path)
            validation_store = RecipeValidationStore(db_path)
            record_recipe_validation_results(
                store=validation_store,
                manifest=manifest,
                results=(("FIXTURE", True, "ok"),),
            )
            telemetry.record_attempt(
                task_id="task-1",
                capability_id="SEARCH_TWEETS",
                release_id=manifest.release_id,
                recipe_revision_id=recipe_revision_id,
                state="FAILURE",
                session_id="session-1",
                error_class="OPERATION_NOT_FOUND",
            )

            report = build_protocol_drift_report(
                manifest=manifest,
                release_store=releases,
                telemetry_store=telemetry,
                validation_store=validation_store,
            )

            self.assertTrue(report["drifting"])
            self.assertEqual(report["severity"], "HIGH")
            self.assertEqual(report["operator_action"], "quarantine_release_and_refresh_protocol_operation")
            self.assertEqual(report["signals"][0]["error_class"], "OPERATION_NOT_FOUND")

    def test_drift_report_flags_high_recent_failure_rate_without_hard_signal(self):
        manifest = load_manifest()
        recipe_revision_id = manifest.bindings[0].recipe.revision_id
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            releases = ReleaseStore(db_path)
            telemetry = ProtocolTelemetryStore(db_path)
            validation_store = RecipeValidationStore(db_path)
            record_recipe_validation_results(
                store=validation_store,
                manifest=manifest,
                results=(("FIXTURE", True, "ok"),),
            )
            for index in range(5):
                telemetry.record_attempt(
                    task_id=f"task-{index}",
                    capability_id="SEARCH_TWEETS",
                    release_id=manifest.release_id,
                    recipe_revision_id=recipe_revision_id,
                    state="FAILURE" if index < 3 else "SUCCESS",
                    session_id="session-1",
                    error_class="UNEXPECTED_HTTP_STATUS" if index < 3 else None,
                )

            report = build_protocol_drift_report(
                manifest=manifest,
                release_store=releases,
                telemetry_store=telemetry,
                validation_store=validation_store,
            )

            self.assertTrue(report["drifting"])
            self.assertEqual(report["severity"], "MEDIUM")
            self.assertEqual(report["failures_in_window"], 3)
            self.assertEqual(report["attempts_in_window"], 5)

    def test_drift_report_healthy_when_recent_attempts_all_succeed(self):
        manifest = load_manifest()
        recipe_revision_id = manifest.bindings[0].recipe.revision_id
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            releases = ReleaseStore(db_path)
            telemetry = ProtocolTelemetryStore(db_path)
            validation_store = RecipeValidationStore(db_path)
            record_recipe_validation_results(
                store=validation_store,
                manifest=manifest,
                results=(("FIXTURE", True, "ok"), ("CAPTURE_REPLAY", True, "ok")),
            )
            for index in range(5):
                telemetry.record_attempt(
                    task_id=f"task-{index}",
                    capability_id="SEARCH_TWEETS",
                    release_id=manifest.release_id,
                    recipe_revision_id=recipe_revision_id,
                    state="SUCCESS",
                    session_id="session-1",
                )

            report = build_protocol_drift_report(
                manifest=manifest,
                release_store=releases,
                telemetry_store=telemetry,
                validation_store=validation_store,
            )

            self.assertFalse(report["drifting"])
            self.assertEqual(report["severity"], "LOW")
            self.assertTrue(report["recipe_fresh"])
            self.assertIsNotNone(report["last_success_at"])
            self.assertIsNone(report["last_failure_at"])

    def test_drift_report_ignores_failures_outside_the_recency_window(self):
        manifest = load_manifest()
        recipe_revision_id = manifest.bindings[0].recipe.revision_id
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            releases = ReleaseStore(db_path)
            telemetry = ProtocolTelemetryStore(db_path)
            validation_store = RecipeValidationStore(db_path)
            record_recipe_validation_results(
                store=validation_store,
                manifest=manifest,
                results=(("FIXTURE", True, "ok"), ("CAPTURE_REPLAY", True, "ok")),
            )
            for index in range(3):
                telemetry.record_attempt(
                    task_id=f"old-failure-{index}",
                    capability_id="SEARCH_TWEETS",
                    release_id=manifest.release_id,
                    recipe_revision_id=recipe_revision_id,
                    state="FAILURE",
                    session_id="session-1",
                    error_class="RATE_LIMITED",
                )
            for index in range(5):
                telemetry.record_attempt(
                    task_id=f"recent-success-{index}",
                    capability_id="SEARCH_TWEETS",
                    release_id=manifest.release_id,
                    recipe_revision_id=recipe_revision_id,
                    state="SUCCESS",
                    session_id="session-1",
                )

            report = build_protocol_drift_report(
                manifest=manifest,
                release_store=releases,
                telemetry_store=telemetry,
                validation_store=validation_store,
                window=5,
            )

            self.assertFalse(report["drifting"])
            self.assertEqual(report["attempts_in_window"], 5)
            self.assertEqual(report["failures_in_window"], 0)

    def test_drift_report_flags_stale_recipe_validation_when_otherwise_healthy(self):
        manifest = load_manifest()
        recipe_revision_id = manifest.bindings[0].recipe.revision_id
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            releases = ReleaseStore(db_path)
            telemetry = ProtocolTelemetryStore(db_path)
            validation_store = RecipeValidationStore(db_path)
            # No validation record persisted for this recipe at all.
            telemetry.record_attempt(
                task_id="task-1",
                capability_id="SEARCH_TWEETS",
                release_id=manifest.release_id,
                recipe_revision_id=recipe_revision_id,
                state="SUCCESS",
                session_id="session-1",
            )

            report = build_protocol_drift_report(
                manifest=manifest,
                release_store=releases,
                telemetry_store=telemetry,
                validation_store=validation_store,
            )

            self.assertTrue(report["drifting"])
            self.assertEqual(report["severity"], "MEDIUM")
            self.assertFalse(report["recipe_fresh"])

    def test_drift_report_reports_no_signal_when_no_attempts_recorded(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            releases = ReleaseStore(db_path)
            telemetry = ProtocolTelemetryStore(db_path)
            validation_store = RecipeValidationStore(db_path)

            report = build_protocol_drift_report(
                manifest=manifest,
                release_store=releases,
                telemetry_store=telemetry,
                validation_store=validation_store,
            )

            self.assertFalse(report["drifting"])
            self.assertEqual(report["attempts_in_window"], 0)
            self.assertIn("No recent telemetry attempts", report["reason"])


if __name__ == "__main__":
    unittest.main()
