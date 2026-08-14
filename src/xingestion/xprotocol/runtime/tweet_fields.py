from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class TweetRecord:
    tweet_id: str
    username: str
    name: str
    text: str
    source_created_at: str
    reply_count: int
    repost_count: int
    like_count: int
    quote_count: int
    bookmark_count: int
    view_count: str | None
    media_urls: tuple[str, ...]
    canonical_url: str


def make_tweet_record(result: Any) -> TweetRecord | None:
    """Extract a TweetRecord from one GraphQL `Tweet`/`TweetWithVisibilityResults`
    result node. Shared by every capability that surfaces tweet objects
    (SearchTimeline, TweetResultByRestId, ...), since X nests the same
    `legacy`/`core`/`rest_id` shape under each.
    """
    if not isinstance(result, Mapping):
        return None

    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", {})

    legacy = result.get("legacy")
    if not isinstance(legacy, Mapping):
        return None

    tweet_id = str(result.get("rest_id") or legacy.get("id_str") or "")
    if not tweet_id:
        return None

    user_result = (
        result
        .get("core", {})
        .get("user_results", {})
        .get("result", {})
    )
    user_core = user_result.get("core", {})
    user_legacy = user_result.get("legacy", {})

    username = str(user_core.get("screen_name") or user_legacy.get("screen_name") or "")
    name = str(user_core.get("name") or user_legacy.get("name") or "")
    return TweetRecord(
        tweet_id=tweet_id,
        username=username,
        name=name,
        text=str(legacy.get("full_text", "")),
        source_created_at=str(legacy.get("created_at", "")),
        reply_count=_int_value(legacy.get("reply_count")),
        repost_count=_int_value(legacy.get("retweet_count")),
        like_count=_int_value(legacy.get("favorite_count")),
        quote_count=_int_value(legacy.get("quote_count")),
        bookmark_count=_int_value(legacy.get("bookmark_count")),
        view_count=_view_count(result),
        media_urls=_media_urls(legacy),
        canonical_url=(
            f"https://x.com/{username}/status/{tweet_id}"
            if username
            else ""
        ),
    )


def merge_tweet_records(existing: TweetRecord, incoming: TweetRecord) -> TweetRecord:
    return TweetRecord(
        tweet_id=existing.tweet_id,
        username=incoming.username or existing.username,
        name=incoming.name or existing.name,
        text=incoming.text if len(incoming.text) > len(existing.text) else existing.text,
        source_created_at=incoming.source_created_at or existing.source_created_at,
        reply_count=max(existing.reply_count, incoming.reply_count),
        repost_count=max(existing.repost_count, incoming.repost_count),
        like_count=max(existing.like_count, incoming.like_count),
        quote_count=max(existing.quote_count, incoming.quote_count),
        bookmark_count=max(existing.bookmark_count, incoming.bookmark_count),
        view_count=_better_view_count(existing.view_count, incoming.view_count),
        media_urls=incoming.media_urls or existing.media_urls,
        canonical_url=incoming.canonical_url or existing.canonical_url,
    )


def _view_count(result: Mapping[str, Any]) -> str | None:
    views = result.get("views")
    if isinstance(views, Mapping):
        count = views.get("count")
        if count not in (None, ""):
            return str(count)
    return None


def _better_view_count(existing: str | None, incoming: str | None) -> str | None:
    if existing in (None, ""):
        return incoming
    if incoming in (None, ""):
        return existing
    if str(existing).isdigit() and str(incoming).isdigit():
        return str(max(int(existing), int(incoming)))
    return incoming or existing


def _media_urls(legacy: Mapping[str, Any]) -> tuple[str, ...]:
    media_items = legacy.get("extended_entities", {}).get("media", [])
    if not media_items:
        media_items = legacy.get("entities", {}).get("media", [])

    urls = []
    for item in media_items:
        media_url = item.get("media_url_https") or item.get("media_url")
        expanded_url = item.get("expanded_url")
        if media_url:
            urls.append(str(media_url))
        elif expanded_url:
            urls.append(str(expanded_url))
    return tuple(urls)


def _int_value(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(value)
