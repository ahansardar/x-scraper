import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.releases import ReleaseHealth, ReleaseStore


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


if __name__ == "__main__":
    unittest.main()
