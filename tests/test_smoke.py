import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.smoke import SmokeClient


class FakeSmokeClient(SmokeClient):
    def __init__(self):
        super().__init__(base_url="http://test")
        self.posts = []

    def _get(self, path):
        responses = {
            "/api/health": {"release_id": "release-1", "auth_ready": True},
            "/api/metrics": {
                "tasks": {"active": 0},
                "canonical": {"canonical_tweets": 3},
            },
            "/api/storage": {
                "sqlite_path": "data/tasks.sqlite3",
                "raw_evidence_dir": "data/raw_evidence",
            },
            "/api/releases/current": {"release": {"health": "ACTIVE"}},
            "/api/sessions": {"sessions": [{"session_id": "local"}]},
            "/api/tasks/task-1/result": {
                "task": {"state": "DONE"},
                "page": {"tweets": [{"tweet_id": "1"}]},
            },
            "/api/canonical/tweets": {
                "counts": {
                    "canonical_tweets": 4,
                    "engagement_observations": 4,
                }
            },
        }
        return responses[path]

    def _post(self, path, payload):
        self.posts.append((path, payload))
        return {
            "task": {"task_id": "task-1"},
            "result_url": "/api/tasks/task-1/result",
        }


class SmokeTests(unittest.TestCase):
    def test_health_only_smoke_reports_core_surfaces(self):
        result = FakeSmokeClient().run()

        self.assertTrue(result.ok)
        self.assertTrue(any("health ok" in message for message in result.messages))
        self.assertTrue(any("metrics active_tasks" in message for message in result.messages))

    def test_submit_smoke_posts_real_capability_payload_shape(self):
        client = FakeSmokeClient()

        result = client.run(submit_query="india lang:en")

        self.assertTrue(result.ok)
        self.assertEqual(client.posts[0][0], "/api/capability-tasks")
        self.assertEqual(client.posts[0][1]["capability_id"], "SEARCH_TWEETS")
        self.assertTrue(any("result state=DONE" in message for message in result.messages))


if __name__ == "__main__":
    unittest.main()
