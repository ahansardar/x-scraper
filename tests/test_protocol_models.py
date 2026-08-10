import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xrev.protocol import CapabilityId, ProtocolReleaseManifest, RevisionStatus



class ProtocolModelTests(unittest.TestCase):
    def test_loads_search_tweets_candidate_manifest(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )

        self.assertEqual(
            manifest.release_id,
            "xrev-search-tweets-2026-08-10-candidate-1",
        )
        self.assertEqual(manifest.status, RevisionStatus.CANDIDATE)
        self.assertEqual(len(manifest.bindings), 1)
        self.assertEqual(manifest.bindings[0].capability_id, CapabilityId.SEARCH_TWEETS)

    def test_recipe_composition_hash_is_deterministic(self):
        path = ROOT / "protocol_releases" / "search_tweets.candidate.json"
        first = ProtocolReleaseManifest.from_file(path)
        second = ProtocolReleaseManifest.from_file(path)

        self.assertEqual(
            first.bindings[0].recipe.composition_hash,
            second.bindings[0].recipe.composition_hash,
        )
        self.assertEqual(
            first.bindings[0].recipe.operation.content_hash,
            second.bindings[0].recipe.operation.content_hash,
        )

    def test_feature_bundle_is_immutable_after_loading(self):
        manifest = ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        )
        feature_bundle = manifest.bindings[0].recipe.feature_bundle

        with self.assertRaises(TypeError):
            feature_bundle.features["view_counts_everywhere_api_enabled"] = False

        with self.assertRaises(FrozenInstanceError):
            feature_bundle.revision_id = "changed"


if __name__ == "__main__":
    unittest.main()
