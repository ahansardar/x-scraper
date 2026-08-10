import json
import tempfile
import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.capabilities import CapabilityPlanner
from xingestion.tasks import SQLiteTaskLedger
from xingestion.web import live_server
from xrev.protocol import ProtocolReleaseManifest


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
                    },
                    "idempotency_key": "northbound-1",
                }
            )

            self.assertEqual(handler.status, 202)
            self.assertEqual(payload["task"]["capability_id"], "SEARCH_TWEETS")
            self.assertEqual(payload["status_url"], f"/api/tasks/{payload['task']['task_id']}")

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


if __name__ == "__main__":
    unittest.main()
