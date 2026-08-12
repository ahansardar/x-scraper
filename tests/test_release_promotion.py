import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.releases import (
    ReleaseHealth,
    ReleaseStore,
    build_promotion_safety_report,
)
from xingestion.xprotocol.protocol import ProtocolReleaseManifest


class ReleasePromotionTests(unittest.TestCase):
    def test_promotion_safety_passes_for_current_fixture_release(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            store = ReleaseStore(db_path)
            store.approve_release(manifest.release_id, reason="test")

            report = build_promotion_safety_report(
                release_id=manifest.release_id,
                manifest=manifest,
                release_store=store,
                manifest_dir=ROOT / "protocol_releases",
                raw_evidence_dir=Path(temp_dir) / "raw",
            )

            self.assertTrue(report.ok)
            checks = {check.name: check.ok for check in report.checks}
            self.assertTrue(checks["manifest_present"])
            self.assertTrue(checks["fixture_validation"])
            self.assertTrue(checks["capture_replay_comparison"])

    def test_promotion_safety_blocks_quarantined_release(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tasks.sqlite3"
            store = ReleaseStore(db_path)
            store.set_health(
                manifest.release_id,
                health=ReleaseHealth.QUARANTINED,
                reason="test",
            )

            report = build_promotion_safety_report(
                release_id=manifest.release_id,
                manifest=manifest,
                release_store=store,
                manifest_dir=ROOT / "protocol_releases",
                raw_evidence_dir=Path(temp_dir) / "raw",
            )

            self.assertFalse(report.ok)
            failed = [check.name for check in report.checks if not check.ok]
            self.assertIn("release_health_allows_execution", failed)


if __name__ == "__main__":
    unittest.main()
