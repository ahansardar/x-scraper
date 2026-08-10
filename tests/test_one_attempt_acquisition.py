import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xrev.evidence import FileRawEvidenceSink
from xrev.protocol import ProtocolReleaseManifest
from xrev.runtime import (
    ProtocolError,
    ProtocolHttpResponse,
    RetryDisposition,
    SearchTweetsRequest,
    WebSessionAuth,
    acquire_search_tweets_page,
)


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        return self.response


def load_recipe():
    manifest = ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )
    return manifest.bindings[0].recipe


class OneAttemptAcquisitionTests(unittest.TestCase):
    def test_success_executes_once_stores_evidence_then_parses(self):
        payload = {"data": {"timeline": [{"cursorType": "Bottom", "value": "next"}]}}
        transport = RecordingTransport(ProtocolHttpResponse(200, payload))

        with tempfile.TemporaryDirectory() as temp_dir:
            page = acquire_search_tweets_page(
                recipe=load_recipe(),
                auth=WebSessionAuth("auth-token", "csrf-token", "bearer-token"),
                request=SearchTweetsRequest(query="india"),
                transport=transport,
                raw_evidence_sink=FileRawEvidenceSink(temp_dir),
            )

            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(page.next_cursor, "next")
            self.assertIsNotNone(page.raw_evidence_ref)
            self.assertTrue(Path(page.raw_evidence_ref.storage_uri).exists())
            self.assertEqual(
                page.raw_evidence_ref.metadata["capability_id"],
                "SEARCH_TWEETS",
            )

    def test_http_error_is_typed_and_does_not_store_evidence(self):
        transport = RecordingTransport(
            ProtocolHttpResponse(429, {"errors": ["limited"]}, {"retry-after": "30"})
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ProtocolError) as raised:
                acquire_search_tweets_page(
                    recipe=load_recipe(),
                    auth=WebSessionAuth("auth-token", "csrf-token", "bearer-token"),
                    request=SearchTweetsRequest(query="india"),
                    transport=transport,
                    raw_evidence_sink=FileRawEvidenceSink(temp_dir),
                )

            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(raised.exception.error_class, "RATE_LIMITED")
            self.assertEqual(
                raised.exception.retry_disposition,
                RetryDisposition.RETRY_AFTER,
            )
            self.assertEqual(raised.exception.retry_after_seconds, 30)
            self.assertEqual(list(Path(temp_dir).glob("*")), [])

    def test_operation_404_is_non_retryable_operation_error(self):
        transport = RecordingTransport(ProtocolHttpResponse(404, {"errors": []}))

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ProtocolError) as raised:
                acquire_search_tweets_page(
                    recipe=load_recipe(),
                    auth=WebSessionAuth("auth-token", "csrf-token", "bearer-token"),
                    request=SearchTweetsRequest(query="india"),
                    transport=transport,
                    raw_evidence_sink=FileRawEvidenceSink(temp_dir),
                )

            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(raised.exception.error_class, "OPERATION_NOT_FOUND")
            self.assertEqual(raised.exception.retry_disposition, RetryDisposition.NEVER)
            self.assertEqual(raised.exception.scope_hint, "OPERATION")


if __name__ == "__main__":
    unittest.main()
