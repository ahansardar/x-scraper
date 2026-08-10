from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from xrev.evidence import RawEvidenceRef
from xrev.protocol import AcquisitionRecipeRevision


@dataclass(frozen=True)
class WebSessionAuth:
    auth_token: str
    ct0: str
    bearer_token: str

    def missing_fields(self) -> tuple[str, ...]:
        missing = []
        if not self.auth_token:
            missing.append("auth_token")
        if not self.ct0:
            missing.append("ct0")
        if not self.bearer_token:
            missing.append("bearer_token")
        return tuple(missing)


@dataclass(frozen=True)
class SearchTweetsRequest:
    query: str
    product: str = "Top"
    count: int = 20
    cursor: str | None = None


@dataclass(frozen=True)
class ProtocolHttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    json_body: Mapping[str, Any]


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
    view_count: str
    media_urls: tuple[str, ...]
    canonical_url: str


@dataclass(frozen=True)
class SearchTweetsPage:
    tweets: tuple[TweetRecord, ...]
    next_cursor: str | None
    raw_evidence_ref: RawEvidenceRef | None = None


def build_search_timeline_request(
    recipe: AcquisitionRecipeRevision,
    auth: WebSessionAuth,
    request: SearchTweetsRequest,
) -> ProtocolHttpRequest:
    missing = auth.missing_fields()
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Missing required auth material: {joined}")

    if request.count < 1 or request.count > 50:
        raise ValueError("count must be between 1 and 50")

    variables: dict[str, Any] = {
        "rawQuery": request.query,
        "count": request.count,
        "querySource": "typed_query",
        "product": request.product,
        "withGrokTranslatedBio": True,
        "withQuickPromoteEligibilityTweetFields": False,
    }
    if request.cursor:
        variables["cursor"] = request.cursor

    body = {
        "variables": variables,
        "features": dict(recipe.feature_bundle.features),
        "fieldToggles": dict(recipe.feature_bundle.field_toggles),
    }

    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "authorization": f"Bearer {auth.bearer_token}",
        "x-csrf-token": auth.ct0,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
        "cookie": f"auth_token={auth.auth_token}; ct0={auth.ct0}",
        "referer": "https://x.com/search",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }

    url = recipe.operation.url_template.format(
        operation_id=recipe.operation.operation_id
    )
    return ProtocolHttpRequest(
        method=recipe.operation.method,
        url=url,
        headers=headers,
        json_body=body,
    )


def parse_search_tweets_page(
    payload: Mapping[str, Any],
    *,
    raw_evidence_ref: RawEvidenceRef | None = None,
) -> SearchTweetsPage:
    tweets: list[TweetRecord] = []
    seen_ids: set[str] = set()
    _find_tweets(payload, tweets, seen_ids)
    return SearchTweetsPage(
        tweets=tuple(tweets),
        next_cursor=_find_bottom_cursor(payload),
        raw_evidence_ref=raw_evidence_ref,
    )


def _find_tweets(obj: Any, tweets: list[TweetRecord], seen_ids: set[str]) -> None:
    if isinstance(obj, Mapping):
        if "tweet_results" in obj:
            result = obj.get("tweet_results", {}).get("result", {})
            tweet = _make_tweet(result)
            if tweet and tweet.tweet_id not in seen_ids:
                seen_ids.add(tweet.tweet_id)
                tweets.append(tweet)

        if obj.get("__typename") in ("Tweet", "TweetWithVisibilityResults"):
            tweet = _make_tweet(obj)
            if tweet and tweet.tweet_id not in seen_ids:
                seen_ids.add(tweet.tweet_id)
                tweets.append(tweet)

        for value in obj.values():
            _find_tweets(value, tweets, seen_ids)
        return

    if isinstance(obj, list):
        for item in obj:
            _find_tweets(item, tweets, seen_ids)


def _make_tweet(result: Any) -> TweetRecord | None:
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
    views = str(result.get("views", {}).get("count", ""))

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
        view_count=views,
        media_urls=_media_urls(legacy),
        canonical_url=(
            f"https://x.com/{username}/status/{tweet_id}"
            if username
            else ""
        ),
    )


def _find_bottom_cursor(obj: Any) -> str | None:
    if isinstance(obj, Mapping):
        if obj.get("cursorType") == "Bottom":
            value = obj.get("value")
            if value:
                return str(value)

        for value in obj.values():
            result = _find_bottom_cursor(value)
            if result:
                return result
        return None

    if isinstance(obj, list):
        for item in obj:
            result = _find_bottom_cursor(item)
            if result:
                return result

    return None


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
