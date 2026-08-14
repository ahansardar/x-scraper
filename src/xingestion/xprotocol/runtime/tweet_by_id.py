from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields
from typing import Any, Mapping

from xingestion.xprotocol.evidence import RawEvidenceRef, RawEvidenceSink
from xingestion.xprotocol.protocol import AcquisitionRecipeRevision
from xingestion.xprotocol.runtime.search_tweets import WebSessionAuth
from xingestion.xprotocol.runtime.transport import (
    OneAttemptTransport,
    ProtocolError,
    ProtocolHttpRequest,
    RetryDisposition,
    response_to_protocol_error,
)
from xingestion.xprotocol.runtime.tweet_fields import TweetRecord, make_tweet_record


@dataclass(frozen=True)
class TweetByIdRequest:
    tweet_id: str


@dataclass(frozen=True)
class TweetByIdResult:
    tweet: TweetRecord | None
    found: bool
    unavailable_reason: str | None
    raw_evidence_ref: RawEvidenceRef | None = None


def acquire_tweet_by_id(
    recipe: AcquisitionRecipeRevision,
    auth: WebSessionAuth,
    request: TweetByIdRequest,
    *,
    transport: OneAttemptTransport,
    raw_evidence_sink: RawEvidenceSink,
) -> TweetByIdResult:
    http_request = build_tweet_by_id_request(recipe, auth, request)
    response = transport.send(http_request)
    error = response_to_protocol_error(response)
    if error:
        raise error

    evidence_ref = raw_evidence_sink.store_json(
        response.json_body,
        metadata={
            "capture_kind": "browser",
            "capability_id": "TWEET_BY_ID",
            "recipe_revision_id": recipe.revision_id,
            "operation_revision_id": recipe.operation.revision_id,
            "parser_revision_id": recipe.parser.revision_id,
            "pagination_revision_id": recipe.pagination.revision_id,
            "acquisition_tweet_id": request.tweet_id,
        },
    )
    result = parse_tweet_by_id_result(response.json_body, raw_evidence_ref=evidence_ref)
    if not result.found:
        if result.unavailable_reason in ("NOT_FOUND", "TOMBSTONE", "UNPARSEABLE"):
            raise ProtocolError(
                error_class="OBJECT_NOT_FOUND",
                message=f"Tweet {request.tweet_id} was not found or has been deleted",
                retry_disposition=RetryDisposition.NEVER,
                scope_hint="PROTOCOL",
            )
        raise ProtocolError(
            error_class="ACCESS_NOT_AUTHORIZED",
            message=(
                f"Tweet {request.tweet_id} is unavailable: "
                f"{result.unavailable_reason}"
            ),
            retry_disposition=RetryDisposition.NEVER,
            scope_hint="PROTOCOL",
        )
    return result


def build_tweet_by_id_request(
    recipe: AcquisitionRecipeRevision,
    auth: WebSessionAuth,
    request: TweetByIdRequest,
) -> ProtocolHttpRequest:
    missing = auth.missing_fields()
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Missing required auth material: {joined}")

    if not request.tweet_id.strip().isdigit():
        raise ValueError("tweet_id must be a non-empty numeric string")

    variables: dict[str, Any] = {
        "tweetId": request.tweet_id,
        "withCommunity": False,
        "includePromotedContent": False,
        "withVoice": False,
    }

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
        "referer": f"https://x.com/i/status/{request.tweet_id}",
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


def validate_tweet_by_id_recipe_binding(recipe: AcquisitionRecipeRevision) -> tuple[str, ...]:
    """Same self-check as `search_tweets.validate_recipe_binding()`, bound to
    `build_tweet_by_id_request()` instead: catches a recipe whose declared
    auth/header metadata has drifted from what the request builder actually
    does, before that drift is only discovered via a live rejected request.
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
    probe_request = TweetByIdRequest(tweet_id="1234567890")
    try:
        built = build_tweet_by_id_request(recipe, probe_auth, probe_request)
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
            f"which build_tweet_by_id_request() never sets"
        )

    if not built.url or recipe.operation.operation_id not in built.url:
        problems.append(
            f"built request URL does not reference operation_id={recipe.operation.operation_id!r}"
        )

    return tuple(problems)


def parse_tweet_by_id_result(
    payload: Mapping[str, Any],
    *,
    raw_evidence_ref: RawEvidenceRef | None = None,
) -> TweetByIdResult:
    result = payload.get("data", {}).get("tweetResult", {}).get("result")
    if not isinstance(result, Mapping) or not result:
        return TweetByIdResult(
            tweet=None,
            found=False,
            unavailable_reason="NOT_FOUND",
            raw_evidence_ref=raw_evidence_ref,
        )

    typename = result.get("__typename")
    if typename == "TweetTombstone":
        return TweetByIdResult(
            tweet=None,
            found=False,
            unavailable_reason="TOMBSTONE",
            raw_evidence_ref=raw_evidence_ref,
        )
    if typename == "TweetUnavailable":
        reason = str(result.get("reason") or "UNAVAILABLE")
        return TweetByIdResult(
            tweet=None,
            found=False,
            unavailable_reason=reason,
            raw_evidence_ref=raw_evidence_ref,
        )

    tweet = make_tweet_record(result)
    if tweet is None:
        return TweetByIdResult(
            tweet=None,
            found=False,
            unavailable_reason="UNPARSEABLE",
            raw_evidence_ref=raw_evidence_ref,
        )

    return TweetByIdResult(
        tweet=tweet,
        found=True,
        unavailable_reason=None,
        raw_evidence_ref=raw_evidence_ref,
    )
