import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.supervision import DeploymentSupervisorCheck


class FakeApiClient:
    def __init__(self, responses):
        self.responses = responses

    def get(self, path):
        if path not in self.responses:
            raise RuntimeError(f"missing {path}")
        return self.responses[path]


class FakeProcessProbe:
    def __init__(self, commands):
        self.commands = tuple(commands)

    def command_lines(self):
        return self.commands


class SupervisionTests(unittest.TestCase):
    def test_supervisor_check_passes_ready_deployment_with_processes(self):
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(_ready_payloads()),
            root=ROOT,
            process_probe=FakeProcessProbe(
                [
                    r"python F:\x-scraper\run_app.py --host 0.0.0.0 --port 8000",
                    r"python F:\x-scraper\run_worker.py",
                    r"python F:\x-scraper\run_dispatcher.py",
                ]
            ),
            expect_processes=True,
        )

        result = checker.run()

        statuses = {check.name: check.status for check in result.checks}
        self.assertTrue(result.ok)
        self.assertEqual(statuses["web"], "PASS")
        self.assertEqual(statuses["startup"], "PASS")
        self.assertEqual(statuses["processes"], "PASS")
        self.assertEqual(statuses["redis_queue"], "PASS")
        self.assertEqual(statuses["recipe_validation_freshness"], "PASS")
        self.assertEqual(statuses["protocol_drift"], "PASS")
        self.assertEqual(statuses["search_route_monitoring"], "PASS")

    def test_supervisor_check_fails_backlogged_outbox(self):
        payloads = _ready_payloads()
        payloads["/api/metrics"]["outbox"] = {
            "unpublished_events": 1,
            "oldest_unpublished_lag_seconds": 999,
        }
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
            max_outbox_lag_seconds=300,
        )

        result = checker.run()

        queue = next(check for check in result.checks if check.name == "queue")
        self.assertFalse(result.ok)
        self.assertEqual(queue.status, "FAIL")

    def test_supervisor_check_fails_backlogged_redis_pending_entries(self):
        payloads = _ready_payloads()
        payloads["/api/metrics"]["redis_queue"]["pending_count"] = 500
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
            max_redis_pending_entries=100,
        )

        result = checker.run()

        redis_queue = next(check for check in result.checks if check.name == "redis_queue")
        self.assertFalse(result.ok)
        self.assertEqual(redis_queue.status, "FAIL")
        self.assertIn("pending_count=500", redis_queue.message)

    def test_supervisor_check_fails_stale_redis_pending_entry(self):
        payloads = _ready_payloads()
        payloads["/api/metrics"]["redis_queue"]["pending_count"] = 1
        payloads["/api/metrics"]["redis_queue"]["oldest_pending_idle_ms"] = 999_000
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
            max_redis_pending_idle_seconds=300,
        )

        result = checker.run()

        redis_queue = next(check for check in result.checks if check.name == "redis_queue")
        self.assertFalse(result.ok)
        self.assertEqual(redis_queue.status, "FAIL")
        self.assertIn("oldest_pending_idle_seconds=999", redis_queue.message)

    def test_supervisor_check_warns_when_redis_consumer_group_missing(self):
        payloads = _ready_payloads()
        payloads["/api/metrics"]["redis_queue"] = {
            "stream_key": "xingestion:capability-tasks",
            "group_name": "capability-workers",
            "group_exists": False,
            "stream_length": 0,
            "pending_count": 0,
            "lag": None,
            "oldest_pending_idle_ms": None,
        }
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
        )

        result = checker.run()

        redis_queue = next(check for check in result.checks if check.name == "redis_queue")
        self.assertTrue(result.ok)
        self.assertEqual(redis_queue.status, "WARN")

    def test_supervisor_check_fails_unavailable_redis_queue_stats(self):
        payloads = _ready_payloads()
        payloads["/api/metrics"]["redis_queue"] = {
            "error": "ConnectionError",
            "message": "connection refused",
        }
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
        )

        result = checker.run()

        redis_queue = next(check for check in result.checks if check.name == "redis_queue")
        self.assertFalse(result.ok)
        self.assertEqual(redis_queue.status, "FAIL")

    def test_supervisor_check_warns_on_stale_recipe_validation(self):
        payloads = _ready_payloads()
        payloads["/api/metrics"]["recipe_validation_freshness"][0]["fresh"] = False
        payloads["/api/metrics"]["recipe_validation_freshness"][0]["reason"] = (
            "no validation record found for this recipe revision"
        )
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
        )

        result = checker.run()

        freshness = next(
            check for check in result.checks if check.name == "recipe_validation_freshness"
        )
        self.assertTrue(result.ok)
        self.assertEqual(freshness.status, "WARN")
        self.assertIn("1/2 stale", freshness.message)

    def test_supervisor_check_warns_when_no_recipe_validation_data(self):
        payloads = _ready_payloads()
        payloads["/api/metrics"]["recipe_validation_freshness"] = []
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
        )

        result = checker.run()

        freshness = next(
            check for check in result.checks if check.name == "recipe_validation_freshness"
        )
        self.assertTrue(result.ok)
        self.assertEqual(freshness.status, "WARN")

    def test_supervisor_check_warns_on_active_protocol_drift(self):
        payloads = _ready_payloads()
        payloads["/api/metrics"]["protocol_drift"]["drifting"] = True
        payloads["/api/metrics"]["protocol_drift"]["severity"] = "HIGH"
        payloads["/api/metrics"]["protocol_drift"]["failures_in_window"] = 3
        payloads["/api/metrics"]["protocol_drift"]["reason"] = (
            "OPERATION_NOT_FOUND appeared 3 time(s) in the last 5 attempts"
        )
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
        )

        result = checker.run()

        drift = next(check for check in result.checks if check.name == "protocol_drift")
        self.assertTrue(result.ok)
        self.assertEqual(drift.status, "WARN")
        self.assertIn("severity=HIGH", drift.message)

    def test_supervisor_check_warns_when_no_protocol_drift_data(self):
        payloads = _ready_payloads()
        payloads["/api/metrics"]["protocol_drift"] = {}
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
        )

        result = checker.run()

        drift = next(check for check in result.checks if check.name == "protocol_drift")
        self.assertTrue(result.ok)
        self.assertEqual(drift.status, "WARN")

    def test_supervisor_check_warns_on_route_remediation_recommendation(self):
        payloads = _ready_payloads()
        payloads["/api/metrics"]["search_route_monitoring"]["action"] = (
            "NETWORK_REMEDIATION_RECOMMENDED"
        )
        payloads["/api/metrics"]["search_route_monitoring"]["reason"] = (
            "Route direct is repeatedly failing with RATE_LIMITED."
        )
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
        )

        result = checker.run()

        route = next(
            check for check in result.checks if check.name == "search_route_monitoring"
        )
        self.assertTrue(result.ok)
        self.assertEqual(route.status, "WARN")

    def test_supervisor_check_fails_on_route_quarantine_recommendation(self):
        payloads = _ready_payloads()
        payloads["/api/metrics"]["search_route_monitoring"]["action"] = (
            "QUARANTINE_RECOMMENDED"
        )
        payloads["/api/metrics"]["search_route_monitoring"]["release_risk_action"] = (
            "QUARANTINE_RECOMMENDED"
        )
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
        )

        result = checker.run()

        route = next(
            check for check in result.checks if check.name == "search_route_monitoring"
        )
        self.assertFalse(result.ok)
        self.assertEqual(route.status, "FAIL")

    def test_supervisor_check_fails_checkout_storage_when_required(self):
        payloads = _ready_payloads()
        payloads["/api/storage"]["data_dir"] = str(ROOT / "data")
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
            require_external_data_dir=True,
        )

        result = checker.run()

        storage = next(check for check in result.checks if check.name == "storage")
        self.assertFalse(result.ok)
        self.assertEqual(storage.status, "FAIL")

    def test_supervisor_check_fails_startup_readiness(self):
        payloads = _ready_payloads()
        payloads["/api/startup"] = {
            "ok": False,
            "checks": [
                {
                    "name": "startup_directories",
                    "status": "FAIL",
                    "message": "logs not writable",
                }
            ],
        }
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
        )

        result = checker.run()

        startup = next(check for check in result.checks if check.name == "startup")
        self.assertFalse(result.ok)
        self.assertEqual(startup.status, "FAIL")
        self.assertIn("logs not writable", startup.message)

    def test_supervisor_check_fails_missing_worker_process_when_expected(self):
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(_ready_payloads()),
            root=ROOT,
            process_probe=FakeProcessProbe([r"python F:\x-scraper\run_app.py"]),
            expect_processes=True,
        )

        result = checker.run()

        processes = next(check for check in result.checks if check.name == "processes")
        self.assertFalse(result.ok)
        self.assertEqual(processes.status, "FAIL")
        self.assertIn("run_worker.py", processes.message)

    def test_supervisor_check_requires_matching_network_session(self):
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(_ready_payloads()),
            root=ROOT,
            required_network_context="proxy:pool-a",
        )

        result = checker.run()

        network = next(check for check in result.checks if check.name == "network")
        self.assertFalse(result.ok)
        self.assertEqual(network.status, "FAIL")
        self.assertIn("proxy:pool-a", network.message)

    def test_supervisor_check_fails_unhealthy_route_after_threshold(self):
        payloads = _ready_payloads()
        payloads["/api/network-health"]["routes"] = [
            {
                "network_context": "direct",
                "total_attempts": 10,
                "successes": 1,
                "failures": 9,
                "failure_rate": 0.9,
                "distinct_sessions": 1,
                "errors_by_class": {"RATE_LIMITED": 9},
            }
        ]
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
            max_network_failure_rate=0.8,
            min_network_attempts=5,
        )

        result = checker.run()

        network = next(check for check in result.checks if check.name == "network")
        self.assertFalse(result.ok)
        self.assertEqual(network.status, "FAIL")
        self.assertIn("failure_rate=0.90", network.message)

    def test_supervisor_check_warns_when_required_route_has_no_attempts(self):
        payloads = _ready_payloads()
        payloads["/api/sessions"]["sessions"][0]["network_context"] = "proxy:pool-a:iad"
        payloads["/api/network-health"]["routes"] = []
        checker = DeploymentSupervisorCheck(
            api_client=FakeApiClient(payloads),
            root=ROOT,
            required_network_context="proxy:pool-a",
        )

        result = checker.run()

        network = next(check for check in result.checks if check.name == "network")
        self.assertTrue(result.ok)
        self.assertEqual(network.status, "WARN")


def _ready_payloads():
    return {
        "/api/health": {
            "ok": True,
            "release_id": "search-tweets-candidate",
            "dispatch": "outbox-local-worker",
        },
        "/api/storage": {
            "data_dir": r"F:\x-scraper-data",
            "sqlite_path": r"F:\x-scraper-data\tasks.sqlite3",
            "raw_evidence_dir": r"F:\x-scraper-data\raw_evidence",
        },
        "/api/startup": {
            "ok": True,
            "checks": [
                {
                    "name": "startup_directories",
                    "status": "PASS",
                    "message": "directories writable",
                }
            ],
        },
        "/api/metrics": {
            "outbox": {
                "unpublished_events": 0,
                "oldest_unpublished_lag_seconds": None,
            },
            "redis_queue": {
                "stream_key": "xingestion:capability-tasks",
                "group_name": "capability-workers",
                "group_exists": True,
                "stream_length": 0,
                "pending_count": 0,
                "lag": 0,
                "oldest_pending_idle_ms": None,
            },
            "recipe_validation_freshness": [
                {
                    "recipe_revision_id": "recipe-a",
                    "composition_hash": "hash-a",
                    "validation_type": "FIXTURE",
                    "fresh": True,
                    "reason": "latest validation record matches current composition and passed",
                    "latest_record": None,
                },
                {
                    "recipe_revision_id": "recipe-a",
                    "composition_hash": "hash-a",
                    "validation_type": "CAPTURE_REPLAY",
                    "fresh": True,
                    "reason": "latest validation record matches current composition and passed",
                    "latest_record": None,
                },
            ],
            "protocol_drift": {
                "release_id": "search-tweets-candidate",
                "recipe_revision_id": "recipe-a",
                "composition_hash": "hash-a",
                "window_size": 20,
                "attempts_in_window": 5,
                "failures_in_window": 0,
                "failure_rate": 0.0,
                "signals": [],
                "last_success_at": "2026-08-11T00:00:00+00:00",
                "last_failure_at": None,
                "recipe_fresh": True,
                "drifting": False,
                "severity": "LOW",
                "reason": "No recent drift signal in the last window of attempts.",
                "operator_action": "continue_monitoring",
            },
            "search_route_monitoring": {
                "release_id": "search-tweets-candidate",
                "release_health": "ACTIVE",
                "network_context": "direct",
                "matched_network_context": "direct",
                "has_route_data": True,
                "route_summary": {
                    "network_context": "direct",
                    "total_attempts": 2,
                    "successes": 2,
                    "failures": 0,
                    "failure_rate": 0.0,
                    "distinct_sessions": 1,
                    "last_attempt_at": "2026-08-11T00:00:00+00:00",
                    "last_success_at": "2026-08-11T00:00:00+00:00",
                    "errors_by_class": {},
                },
                "route_recommendation": None,
                "release_risk_action": "NO_ACTION",
                "action": "CONTINUE_MONITORING",
                "severity": "LOW",
                "reason": "Route direct remains within the approved search-route thresholds.",
                "operator_action": "continue_monitoring",
            },
            "sessions": {
                "healthy": 1,
            },
        },
        "/api/migrations": {
            "migrations": {
                "current": True,
                "applied_versions": ["001"],
                "pending_versions": [],
            },
        },
        "/api/sessions": {
            "sessions": [
                {
                    "session_id": "session-1",
                    "health": "HEALTHY",
                    "network_context": "direct",
                }
            ],
        },
        "/api/network-health": {
            "worker_network_context": None,
            "routes": [
                {
                    "network_context": "direct",
                    "total_attempts": 2,
                    "successes": 2,
                    "failures": 0,
                    "failure_rate": 0.0,
                    "distinct_sessions": 1,
                    "last_attempt_at": "2026-08-11T00:00:00+00:00",
                    "last_success_at": "2026-08-11T00:00:00+00:00",
                    "errors_by_class": {},
                }
            ],
        },
        "/api/releases/current": {
            "release": {
                "release_id": "search-tweets-candidate",
                "health": "ACTIVE",
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
