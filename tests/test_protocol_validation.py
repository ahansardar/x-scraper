import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.protocol_validation import (
    build_protocol_validation_report,
    list_protocol_validation_reports,
    validate_search_tweets_payload,
    write_protocol_validation_report,
)


FIXTURE = ROOT / "tests" / "fixtures" / "search_tweets" / "search_timeline_regression.json"


class ProtocolValidationTests(unittest.TestCase):
    def test_validates_search_tweets_fixture_with_engagements_and_fingerprints(self):
        result = validate_search_tweets_payload(FIXTURE, source_type="fixture")

        self.assertTrue(result.ok)
        self.assertEqual(result.tweet_count, 2)
        self.assertTrue(result.bottom_cursor_present)
        self.assertEqual(result.engagement_complete_count, 2)
        self.assertEqual(result.missing_engagement_count, 0)
        self.assertEqual(len(result.typename_fingerprint), 16)
        self.assertEqual(len(result.structural_fingerprint), 16)
        self.assertEqual(result.warnings, ())

    def test_builds_report_from_fixture_set(self):
        report = build_protocol_validation_report(
            raw_evidence_dir=None,
            parser_revision_id="parser-test",
            include_fixtures=True,
        )

        self.assertTrue(report.ok)
        self.assertGreaterEqual(report.checked_sources, 1)
        self.assertEqual(report.failed_sources, 0)
        self.assertEqual(report.parser_revision_id, "parser-test")

    def test_writes_and_lists_validation_reports(self):
        report = build_protocol_validation_report(
            raw_evidence_dir=None,
            parser_revision_id="parser-test",
            include_fixtures=True,
        )
        with self.subTest("write"):
            import tempfile
            with tempfile.TemporaryDirectory() as temp_dir:
                path = write_protocol_validation_report(
                    report,
                    report_dir=Path(temp_dir),
                )
                reports = list_protocol_validation_reports(Path(temp_dir))

                self.assertTrue(path.exists())
                self.assertEqual(len(reports), 1)
                self.assertEqual(reports[0].name, path.name)
                self.assertTrue(reports[0].ok)


if __name__ == "__main__":
    unittest.main()
