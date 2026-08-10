import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xrev.evidence import FileRawEvidenceSink
from xrev.runtime import parse_search_tweets_page


class RawEvidenceTests(unittest.TestCase):
    def test_file_sink_stores_json_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sink = FileRawEvidenceSink(temp_dir)
            ref = sink.store_json(
                {"ok": True, "items": [1, 2]},
                metadata={
                    "capability_id": "SEARCH_TWEETS",
                    "recipe_revision_id": "recipe.test",
                },
            )

            evidence_path = Path(ref.storage_uri)
            metadata_path = evidence_path.with_name(
                f"{ref.evidence_id}.metadata.json"
            )

            self.assertTrue(evidence_path.exists())
            self.assertTrue(metadata_path.exists())
            self.assertEqual(ref.media_type, "application/json")
            self.assertEqual(len(ref.content_sha256), 64)
            self.assertEqual(
                json.loads(evidence_path.read_text(encoding="utf-8")),
                {"items": [1, 2], "ok": True},
            )
            self.assertEqual(ref.metadata["capability_id"], "SEARCH_TWEETS")

    def test_parser_result_can_carry_raw_evidence_ref(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sink = FileRawEvidenceSink(temp_dir)
            payload = {"data": {"timeline": [{"cursorType": "Bottom", "value": "c"}]}}
            ref = sink.store_json(payload)

            page = parse_search_tweets_page(payload, raw_evidence_ref=ref)

            self.assertEqual(page.next_cursor, "c")
            self.assertEqual(page.raw_evidence_ref, ref)


if __name__ == "__main__":
    unittest.main()
