import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion import __version__ as RUNTIME_VERSION
from xingestion.releases import (
    RecipeValidationStore,
    record_recipe_validation_results,
    recipe_validation_freshness,
)
from xingestion.xprotocol.protocol import ProtocolReleaseManifest


def load_manifest() -> ProtocolReleaseManifest:
    return ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )


class RecipeValidationStoreTests(unittest.TestCase):
    def test_record_validation_round_trips_and_defaults_runtime_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RecipeValidationStore(Path(temp_dir) / "tasks.sqlite3")

            record = store.record_validation(
                release_id="release-a",
                recipe_revision_id="recipe-a",
                composition_hash="hash-a",
                validation_type="fixture",
                ok=True,
                summary="3/3 fixtures passed",
            )

            self.assertEqual(record.release_id, "release-a")
            self.assertEqual(record.recipe_revision_id, "recipe-a")
            self.assertEqual(record.composition_hash, "hash-a")
            self.assertEqual(record.validation_type, "FIXTURE")
            self.assertEqual(record.runtime_version, RUNTIME_VERSION)
            self.assertTrue(record.ok)
            self.assertTrue(record.record_id)
            self.assertTrue(record.created_at)

    def test_record_validation_rejects_empty_identifiers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RecipeValidationStore(Path(temp_dir) / "tasks.sqlite3")
            with self.assertRaises(ValueError):
                store.record_validation(
                    release_id="",
                    recipe_revision_id="recipe-a",
                    composition_hash="hash-a",
                    validation_type="fixture",
                    ok=True,
                    summary="x",
                )
            with self.assertRaises(ValueError):
                store.record_validation(
                    release_id="release-a",
                    recipe_revision_id="",
                    composition_hash="hash-a",
                    validation_type="fixture",
                    ok=True,
                    summary="x",
                )

    def test_list_recent_filters_by_release_and_recipe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RecipeValidationStore(Path(temp_dir) / "tasks.sqlite3")
            store.record_validation(
                release_id="release-a",
                recipe_revision_id="recipe-a",
                composition_hash="hash-a",
                validation_type="fixture",
                ok=True,
                summary="a",
            )
            store.record_validation(
                release_id="release-b",
                recipe_revision_id="recipe-b",
                composition_hash="hash-b",
                validation_type="fixture",
                ok=False,
                summary="b",
            )

            all_records = store.list_recent(limit=10)
            release_a_only = store.list_recent(release_id="release-a")
            recipe_b_only = store.list_recent(recipe_revision_id="recipe-b")

            self.assertEqual(len(all_records), 2)
            self.assertEqual(len(release_a_only), 1)
            self.assertEqual(release_a_only[0].release_id, "release-a")
            self.assertEqual(len(recipe_b_only), 1)
            self.assertEqual(recipe_b_only[0].release_id, "release-b")

    def test_latest_for_recipe_returns_most_recent_matching_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RecipeValidationStore(Path(temp_dir) / "tasks.sqlite3")
            store.record_validation(
                release_id="release-a",
                recipe_revision_id="recipe-a",
                composition_hash="hash-a",
                validation_type="fixture",
                ok=False,
                summary="first",
            )
            store.record_validation(
                release_id="release-a",
                recipe_revision_id="recipe-a",
                composition_hash="hash-a",
                validation_type="fixture",
                ok=True,
                summary="second",
            )
            store.record_validation(
                release_id="release-a",
                recipe_revision_id="recipe-a",
                composition_hash="hash-a",
                validation_type="capture_replay",
                ok=True,
                summary="unrelated type",
            )

            latest = store.latest_for_recipe(
                release_id="release-a", recipe_revision_id="recipe-a", validation_type="fixture"
            )

            self.assertIsNotNone(latest)
            self.assertEqual(latest.summary, "second")
            self.assertIsNone(
                store.latest_for_recipe(release_id="release-a", recipe_revision_id="missing")
            )

    def test_record_recipe_validation_results_persists_one_row_per_binding_and_type(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RecipeValidationStore(Path(temp_dir) / "tasks.sqlite3")

            records = record_recipe_validation_results(
                store=store,
                manifest=manifest,
                results=(
                    ("FIXTURE", True, "3/3 passed"),
                    ("CAPTURE_REPLAY", False, "1/2 matched"),
                ),
            )

            expected = len(manifest.bindings) * 2
            self.assertEqual(len(records), expected)
            binding = manifest.bindings[0]
            fixture = next(r for r in records if r.validation_type == "FIXTURE")
            self.assertEqual(fixture.release_id, manifest.release_id)
            self.assertEqual(fixture.recipe_revision_id, binding.recipe.revision_id)
            self.assertEqual(fixture.composition_hash, binding.recipe.composition_hash)
            self.assertTrue(fixture.ok)
            capture_replay = next(r for r in records if r.validation_type == "CAPTURE_REPLAY")
            self.assertFalse(capture_replay.ok)
            self.assertEqual(len(store.list_recent(limit=10)), expected)

    def test_freshness_flags_missing_validation_record(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RecipeValidationStore(Path(temp_dir) / "tasks.sqlite3")

            freshness = recipe_validation_freshness(store=store, manifest=manifest)

            self.assertEqual(len(freshness), len(manifest.bindings) * 2)
            self.assertTrue(all(not entry.fresh for entry in freshness))
            self.assertTrue(all("no validation record" in entry.reason for entry in freshness))

    def test_freshness_passes_when_composition_matches_and_ok(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RecipeValidationStore(Path(temp_dir) / "tasks.sqlite3")
            record_recipe_validation_results(
                store=store,
                manifest=manifest,
                results=(
                    ("FIXTURE", True, "3/3 passed"),
                    ("CAPTURE_REPLAY", True, "2/2 matched"),
                ),
            )

            freshness = recipe_validation_freshness(store=store, manifest=manifest)

            self.assertTrue(all(entry.fresh for entry in freshness))

    def test_freshness_flags_failed_latest_record(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RecipeValidationStore(Path(temp_dir) / "tasks.sqlite3")
            record_recipe_validation_results(
                store=store,
                manifest=manifest,
                results=(("FIXTURE", False, "1/3 passed"),),
            )

            freshness = recipe_validation_freshness(
                store=store, manifest=manifest, validation_types=("FIXTURE",)
            )

            self.assertFalse(freshness[0].fresh)
            self.assertIn("failed", freshness[0].reason)

    def test_freshness_flags_composition_drift(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RecipeValidationStore(Path(temp_dir) / "tasks.sqlite3")
            binding = manifest.bindings[0]
            store.record_validation(
                release_id=manifest.release_id,
                recipe_revision_id=binding.recipe.revision_id,
                composition_hash="stale-hash-from-before-a-parser-edit",
                validation_type="FIXTURE",
                ok=True,
                summary="validated an older composition",
            )

            freshness = recipe_validation_freshness(
                store=store, manifest=manifest, validation_types=("FIXTURE",)
            )

            self.assertFalse(freshness[0].fresh)
            self.assertIn("composition changed", freshness[0].reason)


if __name__ == "__main__":
    unittest.main()
