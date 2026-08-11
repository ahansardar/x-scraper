import tempfile
import unittest
from pathlib import Path
import sys
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.releases import ReleaseHealth, ReleaseStore, resolve_approved_manifest


class ReleaseStoreTests(unittest.TestCase):
    def test_release_health_defaults_to_active(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ReleaseStore(Path(temp_dir) / "releases.sqlite3")

            release = store.ensure_release("release-1")

            self.assertEqual(release.health, ReleaseHealth.ACTIVE)
            self.assertTrue(store.execution_allowed("release-1"))

    def test_quarantined_release_blocks_execution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ReleaseStore(Path(temp_dir) / "releases.sqlite3")

            store.set_health(
                "release-1",
                health=ReleaseHealth.QUARANTINED,
                reason="drift",
            )

            self.assertFalse(store.execution_allowed("release-1"))

    def test_approved_release_pointer_resolves_exact_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_dir = root / "manifests"
            manifest_dir.mkdir()
            _write_manifest(manifest_dir / "one.json", release_id="release-1")
            _write_manifest(manifest_dir / "two.json", release_id="release-2")
            store = ReleaseStore(root / "releases.sqlite3")
            store.approve_release("release-2", reason="operator_approved")

            resolved = resolve_approved_manifest(
                release_store=store,
                manifest_dir=manifest_dir,
            )

            self.assertEqual(resolved.release_id, "release-2")
            self.assertEqual(resolved.manifest.release_id, "release-2")
            self.assertEqual(resolved.manifest_path.name, "two.json")

    def test_single_manifest_bootstraps_approved_release_pointer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_dir = root / "manifests"
            manifest_dir.mkdir()
            _write_manifest(manifest_dir / "only.json", release_id="release-1")
            store = ReleaseStore(root / "releases.sqlite3")

            resolved = resolve_approved_manifest(
                release_store=store,
                manifest_dir=manifest_dir,
            )

            self.assertEqual(resolved.release_id, "release-1")
            self.assertEqual(store.approved_release_id(), "release-1")

    def test_multiple_manifests_without_approval_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_dir = root / "manifests"
            manifest_dir.mkdir()
            _write_manifest(manifest_dir / "one.json", release_id="release-1")
            _write_manifest(manifest_dir / "two.json", release_id="release-2")
            store = ReleaseStore(root / "releases.sqlite3")

            with self.assertRaisesRegex(ValueError, "No approved protocol release"):
                resolve_approved_manifest(
                    release_store=store,
                    manifest_dir=manifest_dir,
                )


def _write_manifest(path, *, release_id):
    source = json.loads(
        (ROOT / "protocol_releases" / "search_tweets.candidate.json").read_text(
            encoding="utf-8"
        )
    )
    source["release_id"] = release_id
    path.write_text(json.dumps(source), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
