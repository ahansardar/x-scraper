import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.capabilities import CapabilityPlanner, CapabilityRequest, SearchTweetsInput
from xingestion.canonical import CanonicalStore
from xingestion.reprocessing import reprocess_task_evidence
from xingestion.tasks import SQLiteTaskLedger
from xingestion.workers import LocalWorker
from xrev.evidence import FileRawEvidenceSink
from xrev.protocol import CapabilityId, ProtocolReleaseManifest
from xrev.runtime import ProtocolHttpResponse, WebSessionAuth


class FakeTransport:
    def send(self, request):
        return ProtocolHttpResponse(
            200,
            {
                "entries": [
                    {
                        "tweet_results": {
                            "result": {
                                "__typename": "Tweet",
                                "rest_id": "1",
                                "core": {
                                    "user_results": {
                                        "result": {
                                            "core": {
                                                "screen_name": "alice",
                                                "name": "Alice",
                                            }
                                        }
                                    }
                                },
                                "legacy": {
                                    "id_str": "1",
                                    "full_text": "hello",
                                    "created_at": "Mon Aug 10 12:00:00 +0000 2026",
                                    "favorite_count": 7,
                                    "retweet_count": 3,
                                    "reply_count": 2,
                                    "quote_count": 1,
                                    "bookmark_count": 4,
                                },
                                "views": {"count": "50"},
                            }
                        }
                    }
                ]
            },
        )


def load_manifest():
    return ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )


class ReprocessingTests(unittest.TestCase):
    def test_reprocess_completed_task_from_raw_evidence_without_network(self):
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
            store = CanonicalStore(db_path)
            task = ledger.create_task(
                idempotency_key="reprocess-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )
            worker = LocalWorker(
                ledger=ledger,
                manifest=manifest,
                auth=WebSessionAuth("auth", "csrf", "bearer"),
                transport=FakeTransport(),
                raw_evidence_sink=FileRawEvidenceSink(Path(temp_dir) / "raw"),
                canonical_store=store,
            )
            worker.process_one()

            result = reprocess_task_evidence(
                task_id=task.task_id,
                ledger=ledger,
                canonical_store=store,
            )

            self.assertEqual(result.parsed_tweets, 1)
            self.assertEqual(result.canonical_counts["canonical_tweets"], 1)
            self.assertEqual(result.canonical_counts["engagement_observations"], 2)

    def test_reprocess_rejects_incomplete_task(self):
        manifest = load_manifest()
        request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(query="india", page_size=20),
        )
        plan = CapabilityPlanner(manifest).plan(request)

        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = SQLiteTaskLedger(Path(temp_dir) / "tasks.sqlite3")
            store = CanonicalStore(Path(temp_dir) / "tasks.sqlite3")
            task = ledger.create_task(
                idempotency_key="reprocess-incomplete-key",
                capability_id=request.capability_id,
                contract_version=request.contract_version,
                request_json=request.public_dict(),
                plan_json=plan.public_dict(),
            )

            with self.assertRaisesRegex(ValueError, "completed tasks"):
                reprocess_task_evidence(
                    task_id=task.task_id,
                    ledger=ledger,
                    canonical_store=store,
                )


if __name__ == "__main__":
    unittest.main()
