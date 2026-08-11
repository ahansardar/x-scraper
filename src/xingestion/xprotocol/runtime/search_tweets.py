from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from xingestion.xprotocol.evidence import RawEvidenceRef, RawEvidenceSink
from xingestion.xprotocol.protocol import AcquisitionRecipeRevision
from xingestion.xprotocol.runtime.transport import (
    OneAttemptTransport,
    ProtocolError,
    ProtocolHttpRequest,
    RetryDisposition,
    response_to_protocol_error,
)


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


@dataclass(frozen=True)
class SearchTweetsPage:
    tweets: tuple[TweetRecord, ...]
    next_cursor: str | None
    cursor_present: bool = False
    raw_evidence_ref: RawEvidenceRef | None = None


def acquire_search_tweets_page(
    recipe: AcquisitionRecipeRevision,
    auth: WebSessionAuth,
    request: SearchTweetsRequest,
    *,
    transport: OneAttemptTransport,
    raw_evidence_sink: RawEvidenceSink,
) -> SearchTweetsPage:
    http_request = build_search_timeline_request(recipe, auth, request)
    response = transport.send(http_request)
    error = response_to_protocol_error(response)
    if error:
        raise error

    evidence_ref = raw_evidence_sink.store_json(
        response.json_body,
        metadata={
            "capability_id": "SEARCH_TWEETS",
            "recipe_revision_id": recipe.revision_id,
            "operation_revision_id": recipe.operation.revision_id,
            "parser_revision_id": recipe.parser.revision_id,
            "pagination_revision_id": recipe.pagination.revision_id,
        },
    )
    return parse_search_tweets_page(
        response.json_body,
        raw_evidence_ref=evidence_ref,
    )


def validate_search_tweets_pagination(
    page: SearchTweetsPage,
    *,
    expect_more: bool,
    seen_cursors: tuple[str, ...] = (),
    current_cursor: str | None = None,
) -> str | None:
    if not expect_more:
        return page.next_cursor

    if not page.cursor_present:
        raise ProtocolError(
            error_class="PAGINATION_CURSOR_MISSING",
            message="SearchTimeline did not return a bottom cursor for continuation",
            retry_disposition=RetryDisposition.NEVER,
            scope_hint="PAGINATION",
        )

    if page.next_cursor in (None, ""):
        raise ProtocolError(
            error_class="PAGINATION_EMPTY_CONTINUATION",
            message="SearchTimeline returned an empty bottom cursor",
            retry_disposition=RetryDisposition.NEVER,
            scope_hint="PAGINATION",
        )

    if page.next_cursor == current_cursor or page.next_cursor in seen_cursors:
        raise ProtocolError(
            error_class="PAGINATION_CURSOR_LOOP",
            message="SearchTimeline returned a cursor that has already been seen",
            retry_disposition=RetryDisposition.NEVER,
            scope_hint="PAGINATION",
        )

    return page.next_cursor


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
    tweets: dict[str, TweetRecord] = {}
    _find_tweets(payload, tweets)
    next_cursor, cursor_present = _find_bottom_cursor(payload)
    return SearchTweetsPage(
        tweets=tuple(tweets.values()),
        next_cursor=next_cursor,
        cursor_present=cursor_present,
        raw_evidence_ref=raw_evidence_ref,
    )


def _find_tweets(obj: Any, tweets: dict[str, TweetRecord]) -> None:
    if isinstance(obj, Mapping):
        if "tweet_results" in obj:
            result = obj.get("tweet_results", {}).get("result", {})
            tweet = _make_tweet(result)
            if tweet:
                _store_tweet(tweets, tweet)

        if obj.get("__typename") in ("Tweet", "TweetWithVisibilityResults"):
            tweet = _make_tweet(obj)
            if tweet:
                _store_tweet(tweets, tweet)

        for value in obj.values():
            _find_tweets(value, tweets)
        return

    if isinstance(obj, list):
        for item in obj:
            _find_tweets(item, tweets)


def _store_tweet(tweets: dict[str, TweetRecord], tweet: TweetRecord) -> None:
    existing = tweets.get(tweet.tweet_id)
    tweets[tweet.tweet_id] = tweet if existing is None else _merge_tweet(existing, tweet)


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


def _merge_tweet(existing: TweetRecord, incoming: TweetRecord) -> TweetRecord:
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


def _find_bottom_cursor(obj: Any) -> tuple[str | None, bool]:
    if isinstance(obj, Mapping):
        if obj.get("cursorType") == "Bottom":
            value = obj.get("value")
            if value is None:
                return None, True
            return str(value), True

        for value in obj.values():
            result, present = _find_bottom_cursor(value)
            if present:
                return result, True
        return None, False

    if isinstance(obj, list):
        for item in obj:
            result, present = _find_bottom_cursor(item)
            if present:
                return result, True
    return None, False


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
