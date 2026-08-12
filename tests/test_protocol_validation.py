import unittest
from pathlib import Path
import hashlib
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.protocol_validation import (
    build_capture_replay_comparison_report,
    build_protocol_validation_report,
    list_protocol_validation_reports,
    run_direct_replays_for_browser_captures,
    validate_search_tweets_payload,
    write_protocol_validation_report,
)
from xingestion.xprotocol.evidence import FileRawEvidenceSink
from xingestion.xprotocol.protocol import ProtocolReleaseManifest
from xingestion.xprotocol.runtime import ProtocolHttpResponse, WebSessionAuth


FIXTURE = ROOT / "tests" / "fixtures" / "search_tweets" / "search_timeline_regression.json"


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        return self.response


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

    def test_compares_browser_capture_with_direct_replay(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            browser = _write_capture(root, "browser", payload, capture_kind="browser")
            _write_capture(
                root,
                "direct",
                payload,
                capture_kind="direct_replay",
                replay_of_content_sha256=browser,
            )

            report = build_capture_replay_comparison_report(raw_evidence_dir=root)

            self.assertTrue(report.ok)
            self.assertEqual(report.checked_pairs, 1)
            self.assertEqual(report.comparisons[0].mismatches, ())

    def test_capture_replay_comparison_reports_mismatched_payloads(self):
        browser_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        direct_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        direct_payload["data"] = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            browser = _write_capture(root, "browser", browser_payload, capture_kind="browser")
            _write_capture(
                root,
                "direct",
                direct_payload,
                capture_kind="direct_replay",
                replay_of_content_sha256=browser,
            )

            report = build_capture_replay_comparison_report(raw_evidence_dir=root)

            self.assertFalse(report.ok)
            self.assertEqual(report.checked_pairs, 1)
            self.assertIn("direct_replay_parse_failed", report.comparisons[0].mismatches)

    def test_runs_direct_replay_for_replayable_browser_capture(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        transport = RecordingTransport(ProtocolHttpResponse(200, payload))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            browser = _write_capture(
                root,
                "browser",
                payload,
                capture_kind="browser",
                recipe_revision_id=manifest.bindings[0].recipe.revision_id,
                acquisition_query="india",
                acquisition_product="Top",
                acquisition_count="20",
                acquisition_cursor="",
            )

            replay_report = run_direct_replays_for_browser_captures(
                raw_evidence_dir=root,
                manifest=manifest,
                auth=WebSessionAuth("auth-token", "csrf-token", "bearer-token"),
                transport=transport,
                raw_evidence_sink=FileRawEvidenceSink(root),
                limit=1,
            )
            comparison = build_capture_replay_comparison_report(raw_evidence_dir=root)

            self.assertTrue(replay_report.ok)
            self.assertEqual(replay_report.stored, 1)
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(transport.calls[0].json_body["variables"]["rawQuery"], "india")
            self.assertTrue(comparison.ok)
            self.assertEqual(comparison.checked_pairs, 1)
            self.assertEqual(
                _metadata_for_newest_direct_replay(root)["replay_of_content_sha256"],
                browser,
            )


def _write_capture(
    root,
    name,
    payload,
    *,
    capture_kind,
    replay_of_content_sha256=None,
    **metadata_values,
):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    content_sha = hashlib.sha256(encoded).hexdigest()
    path = root / f"{name}.json"
    metadata_path = root / f"{name}.metadata.json"
    path.write_bytes(encoded)
    metadata = {"capture_kind": capture_kind}
    if replay_of_content_sha256 is not None:
        metadata["replay_of_content_sha256"] = replay_of_content_sha256
    metadata.update(metadata_values)
    metadata_path.write_text(
        json.dumps(
            {
                "content_sha256": content_sha,
                "metadata": metadata,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return content_sha


def _metadata_for_newest_direct_replay(root):
    direct_metadata = []
    for path in root.glob("*.metadata.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        metadata = payload.get("metadata") or {}
        if metadata.get("capture_kind") == "direct_replay":
            direct_metadata.append(metadata)
    assert direct_metadata
    return direct_metadata[-1]


if __name__ == "__main__":
    unittest.main()
