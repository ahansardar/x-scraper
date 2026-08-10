from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

from xrev.runtime import SearchTweetsPage


@dataclass(frozen=True)
class CanonicalTweet:
    tweet_id: str
    username: str
    name: str
    text: str
    source_created_at: str
    first_seen_at: str
    last_seen_at: str
    canonical_url: str


@dataclass(frozen=True)
class EngagementObservation:
    observation_id: int
    tweet_id: str
    task_id: str
    captured_at: str
    reply_count: int
    repost_count: int
    like_count: int
    quote_count: int
    bookmark_count: int
    view_count: str | None


class CanonicalStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._initialize()

    def ingest_search_tweets_page(
        self,
        page: SearchTweetsPage,
        *,
        task_id: str,
        release_id: str,
        recipe_revision_id: str,
    ) -> int:
        captured_at = _now()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            for tweet in page.tweets:
                conn.execute(
                    """
                    INSERT INTO canonical_tweets (
                        tweet_id,
                        username,
                        name,
                        text,
                        source_created_at,
                        first_seen_at,
                        last_seen_at,
                        canonical_url,
                        media_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tweet_id) DO UPDATE SET
                        username = excluded.username,
                        name = excluded.name,
                        text = excluded.text,
                        source_created_at = excluded.source_created_at,
                        last_seen_at = excluded.last_seen_at,
                        canonical_url = excluded.canonical_url,
                        media_json = excluded.media_json
                    """,
                    (
                        tweet.tweet_id,
                        tweet.username,
                        tweet.name,
                        tweet.text,
                        tweet.source_created_at,
                        captured_at,
                        captured_at,
                        tweet.canonical_url,
                        json.dumps(list(tweet.media_urls), separators=(",", ":")),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO engagement_observations (
                        tweet_id,
                        task_id,
                        captured_at,
                        reply_count,
                        repost_count,
                        like_count,
                        quote_count,
                        bookmark_count,
                        view_count,
                        raw_evidence_id,
                        release_id,
                        recipe_revision_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tweet.tweet_id,
                        task_id,
                        captured_at,
                        tweet.reply_count,
                        tweet.repost_count,
                        tweet.like_count,
                        tweet.quote_count,
                        tweet.bookmark_count,
                        tweet.view_count,
                        page.raw_evidence_ref.evidence_id if page.raw_evidence_ref else None,
                        release_id,
                        recipe_revision_id,
                    ),
                )
            conn.commit()
        return len(page.tweets)

    def get_tweet(self, tweet_id: str) -> CanonicalTweet | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM canonical_tweets WHERE tweet_id = ?",
                (tweet_id,),
            ).fetchone()
        return _tweet_from_row(row) if row else None

    def latest_engagements(self, *, limit: int = 25) -> tuple[EngagementObservation, ...]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM engagement_observations
                ORDER BY captured_at DESC, observation_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(_engagement_from_row(row) for row in rows)

    def counts(self) -> dict[str, int]:
        with closing(self._connect()) as conn:
            tweets = conn.execute("SELECT COUNT(*) AS count FROM canonical_tweets").fetchone()
            observations = conn.execute(
                "SELECT COUNT(*) AS count FROM engagement_observations"
            ).fetchone()
        return {
            "canonical_tweets": int(tweets["count"]),
            "engagement_observations": int(observations["count"]),
        }

    def _initialize(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS canonical_tweets (
                    tweet_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source_created_at TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    media_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS engagement_observations (
                    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tweet_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    reply_count INTEGER NOT NULL,
                    repost_count INTEGER NOT NULL,
                    like_count INTEGER NOT NULL,
                    quote_count INTEGER NOT NULL,
                    bookmark_count INTEGER NOT NULL,
                    view_count TEXT,
                    raw_evidence_id TEXT,
                    release_id TEXT NOT NULL,
                    recipe_revision_id TEXT NOT NULL,
                    FOREIGN KEY (tweet_id) REFERENCES canonical_tweets(tweet_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_engagement_observations_tweet_time
                ON engagement_observations (tweet_id, captured_at)
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _tweet_from_row(row: sqlite3.Row) -> CanonicalTweet:
    return CanonicalTweet(
        tweet_id=row["tweet_id"],
        username=row["username"],
        name=row["name"],
        text=row["text"],
        source_created_at=row["source_created_at"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        canonical_url=row["canonical_url"],
    )


def _engagement_from_row(row: sqlite3.Row) -> EngagementObservation:
    return EngagementObservation(
        observation_id=int(row["observation_id"]),
        tweet_id=row["tweet_id"],
        task_id=row["task_id"],
        captured_at=row["captured_at"],
        reply_count=int(row["reply_count"]),
        repost_count=int(row["repost_count"]),
        like_count=int(row["like_count"]),
        quote_count=int(row["quote_count"]),
        bookmark_count=int(row["bookmark_count"]),
        view_count=row["view_count"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
