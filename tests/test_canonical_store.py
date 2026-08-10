import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.canonical import CanonicalStore
from xrev.evidence import RawEvidenceRef
from xrev.runtime import SearchTweetsPage, TweetRecord


def make_page(*, like_count=7):
    evidence = RawEvidenceRef(
        evidence_id="raw-1",
        content_sha256="abc",
        media_type="application/json",
        storage_uri="raw.json",
        captured_at="2026-08-10T00:00:00+00:00",
        metadata={},
    )
    return SearchTweetsPage(
        tweets=(
            TweetRecord(
                tweet_id="1",
                username="alice",
                name="Alice",
                text="hello",
                source_created_at="Mon Aug 10 12:00:00 +0000 2026",
                reply_count=2,
                repost_count=3,
                like_count=like_count,
                quote_count=1,
                bookmark_count=4,
                view_count="50",
                media_urls=("https://example.test/image.jpg",),
                canonical_url="https://x.com/alice/status/1",
            ),
        ),
        next_cursor=None,
        raw_evidence_ref=evidence,
    )


class CanonicalStoreTests(unittest.TestCase):
    def test_ingests_tweet_identity_and_engagement_observation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CanonicalStore(Path(temp_dir) / "canonical.sqlite3")

            count = store.ingest_search_tweets_page(
                make_page(),
                task_id="task-1",
                release_id="release-1",
                recipe_revision_id="recipe-1",
            )

            tweet = store.get_tweet("1")
            observations = store.latest_engagements()
            self.assertEqual(count, 1)
            self.assertEqual(tweet.username, "alice")
            self.assertEqual(observations[0].tweet_id, "1")
            self.assertEqual(observations[0].like_count, 7)
            self.assertEqual(store.counts()["canonical_tweets"], 1)
            self.assertEqual(store.counts()["engagement_observations"], 1)

    def test_repeat_ingest_updates_tweet_and_appends_observation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CanonicalStore(Path(temp_dir) / "canonical.sqlite3")

            store.ingest_search_tweets_page(
                make_page(like_count=7),
                task_id="task-1",
                release_id="release-1",
                recipe_revision_id="recipe-1",
            )
            store.ingest_search_tweets_page(
                make_page(like_count=9),
                task_id="task-2",
                release_id="release-1",
                recipe_revision_id="recipe-1",
            )

            self.assertEqual(store.counts()["canonical_tweets"], 1)
            self.assertEqual(store.counts()["engagement_observations"], 2)
            self.assertEqual(store.latest_engagements(limit=1)[0].like_count, 9)


if __name__ == "__main__":
    unittest.main()
