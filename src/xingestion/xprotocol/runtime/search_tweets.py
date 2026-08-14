from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields
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
from xingestion.xprotocol.runtime.tweet_fields import (
    TweetRecord,
    make_tweet_record,
    merge_tweet_records,
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
            "capture_kind": "browser",
            "capability_id": "SEARCH_TWEETS",
            "recipe_revision_id": recipe.revision_id,
            "operation_revision_id": recipe.operation.revision_id,
            "parser_revision_id": recipe.parser.revision_id,
            "pagination_revision_id": recipe.pagination.revision_id,
            "acquisition_query": request.query,
            "acquisition_product": request.product,
            "acquisition_count": str(request.count),
            "acquisition_cursor": request.cursor or "",
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


def validate_recipe_binding(recipe: AcquisitionRecipeRevision) -> tuple[str, ...]:
    """Check the recipe's declared metadata against what the request builder
    actually does, as one bound unit rather than components validated in
    isolation.

    `auth_profile.required_material` and `transaction_profile.
    required_headers` are declarative metadata -- nothing enforces they stay
    in sync with `build_search_timeline_request()`'s real behavior, so a code
    change to header-building or an edited manifest could silently drift
    from what's declared, only ever discovered by a live 401/rejected
    request in production. This builds one real (probe-credentialed) request
    from the recipe and checks the declared metadata against it directly.

    Returns a tuple of human-readable inconsistency descriptions; empty
    means the recipe's components are consistent with each other.
    """
    problems: list[str] = []

    auth_field_names = {field.name for field in dataclass_fields(WebSessionAuth)}
    declared_material = set(recipe.auth_profile.required_material)
    if declared_material != auth_field_names:
        missing = auth_field_names - declared_material
        extra = declared_material - auth_field_names
        if missing:
            problems.append(
                f"auth_profile.required_material is missing {sorted(missing)}, "
                f"which WebSessionAuth actually requires"
            )
        if extra:
            problems.append(
                f"auth_profile.required_material declares {sorted(extra)}, "
                f"which WebSessionAuth does not have"
            )

    probe_auth = WebSessionAuth(
        auth_token="probe-auth-token", ct0="probe-ct0", bearer_token="probe-bearer-token"
    )
    probe_request = SearchTweetsRequest(query="probe", count=1)
    try:
        built = build_search_timeline_request(recipe, probe_auth, probe_request)
    except (ProtocolError, ValueError) as exc:
        problems.append(f"could not build a request from this recipe: {exc}")
        return tuple(problems)

    built_header_names = {name.lower() for name in built.headers}
    missing_headers = [
        header
        for header in recipe.transaction_profile.required_headers
        if header.lower() not in built_header_names
    ]
    if missing_headers:
        problems.append(
            f"transaction_profile.required_headers declares {missing_headers}, "
            f"which build_search_timeline_request() never sets"
        )

    if not built.url or recipe.operation.operation_id not in built.url:
        problems.append(
            f"built request URL does not reference operation_id={recipe.operation.operation_id!r}"
        )

    return tuple(problems)


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
            tweet = make_tweet_record(result)
            if tweet:
                _store_tweet(tweets, tweet)

        if obj.get("__typename") in ("Tweet", "TweetWithVisibilityResults"):
            tweet = make_tweet_record(obj)
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
    tweets[tweet.tweet_id] = tweet if existing is None else merge_tweet_records(existing, tweet)


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
