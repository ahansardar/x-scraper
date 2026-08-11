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
                ]
            ),
            expect_processes=True,
        )

        result = checker.run()

        statuses = {check.name: check.status for check in result.checks}
        self.assertTrue(result.ok)
        self.assertEqual(statuses["web"], "PASS")
        self.assertEqual(statuses["processes"], "PASS")

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
        "/api/metrics": {
            "outbox": {
                "unpublished_events": 0,
                "oldest_unpublished_lag_seconds": None,
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
