import tempfile
import unittest
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.releases import (
    ReleaseHealth,
    ReleaseStore,
    apply_promotion_audit_retention,
    build_promotion_safety_report,
    list_promotion_audits,
    promotion_audit_file,
    read_promotion_audit,
    write_promotion_audit,
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

    def test_promotion_audit_write_list_and_read_are_path_safe(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            config = type(
                "Config",
                (),
                {
                    "data_dir": data_dir,
                    "raw_evidence_dir": Path(temp_dir) / "raw",
                },
            )()
            store = ReleaseStore(Path(temp_dir) / "tasks.sqlite3")
            store.approve_release(manifest.release_id, reason="before")
            approval_before = store.approved_release()
            report = build_promotion_safety_report(
                release_id=manifest.release_id,
                manifest=manifest,
                release_store=store,
                manifest_dir=ROOT / "protocol_releases",
                raw_evidence_dir=config.raw_evidence_dir,
            )

            result = write_promotion_audit(
                config=config,
                action="APPROVE",
                release_id=manifest.release_id,
                manifest_path=ROOT / "protocol_releases" / "search_tweets.candidate.json",
                reason="test_audit",
                safety=report,
                approved=True,
                forced=False,
                approval_before=approval_before,
                approval_after=store.approved_release(),
                message="Promotion approved",
            )
            summaries = list_promotion_audits(config)
            detail = read_promotion_audit(config, result.path.name)

            self.assertTrue(result.path.exists())
            self.assertEqual(summaries[0].package_type, "RELEASE_PROMOTION_AUDIT")
            self.assertEqual(summaries[0].release_id, manifest.release_id)
            self.assertTrue(summaries[0].safety_ok)
            self.assertEqual(detail["package"]["reason"], "test_audit")
            self.assertEqual(promotion_audit_file(config, result.path.name), result.path)
            with self.assertRaises(ValueError):
                read_promotion_audit(config, "..\\secrets.json")
            with self.assertRaises(ValueError):
                read_promotion_audit(config, "failed-task-safe.json")

    def test_promotion_audit_retention_deletes_only_old_audit_files(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            config = type(
                "Config",
                (),
                {
                    "data_dir": data_dir,
                    "raw_evidence_dir": Path(temp_dir) / "raw",
                },
            )()
            store = ReleaseStore(Path(temp_dir) / "tasks.sqlite3")
            report = build_promotion_safety_report(
                release_id=manifest.release_id,
                manifest=manifest,
                release_store=store,
                manifest_dir=ROOT / "protocol_releases",
                raw_evidence_dir=config.raw_evidence_dir,
            )
            old_path = data_dir / "release_promotions" / "promotion-old.json"
            new_path = data_dir / "release_promotions" / "promotion-new.json"
            ignored_path = data_dir / "release_promotions" / "health-report.json"
            write_promotion_audit(
                config=config,
                action="CHECK",
                release_id=manifest.release_id,
                manifest_path=ROOT / "protocol_releases" / "search_tweets.candidate.json",
                reason="old",
                safety=report,
                approved=False,
                forced=False,
                approval_before=None,
                approval_after=None,
                message="old audit",
                output_path=old_path,
            )
            write_promotion_audit(
                config=config,
                action="CHECK",
                release_id=manifest.release_id,
                manifest_path=ROOT / "protocol_releases" / "search_tweets.candidate.json",
                reason="new",
                safety=report,
                approved=False,
                forced=False,
                approval_before=None,
                approval_after=None,
                message="new audit",
                output_path=new_path,
            )
            ignored_path.write_text("{}", encoding="utf-8")
            old_mtime = (datetime.now(UTC) - timedelta(days=3)).timestamp()
            os.utime(old_path, (old_mtime, old_mtime))
            os.utime(ignored_path, (old_mtime, old_mtime))

            dry_run = apply_promotion_audit_retention(config, days=1, dry_run=True)
            result = apply_promotion_audit_retention(config, days=1, dry_run=False)

            self.assertEqual(dry_run.matched_audits, 1)
            self.assertEqual(dry_run.deleted_audits, 0)
            self.assertEqual(result.matched_audits, 1)
            self.assertEqual(result.deleted_audits, 1)
            self.assertFalse(old_path.exists())
            self.assertTrue(new_path.exists())
            self.assertTrue(ignored_path.exists())


if __name__ == "__main__":
    unittest.main()
