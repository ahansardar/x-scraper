from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol


class RetryDisposition(StrEnum):
    NEVER = "NEVER"
    MAY_RETRY = "MAY_RETRY"
    RETRY_AFTER = "RETRY_AFTER"


@dataclass(frozen=True)
class ProtocolHttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    json_body: Mapping[str, Any]


@dataclass(frozen=True)
class ProtocolHttpResponse:
    status_code: int
    json_body: Mapping[str, Any]
    headers: Mapping[str, str] | None = None


@dataclass(frozen=True)
class ProtocolError(Exception):
    error_class: str
    message: str
    retry_disposition: RetryDisposition
    status_code: int | None = None
    retry_after_seconds: int | None = None
    scope_hint: str = "UNKNOWN"

    def __str__(self) -> str:
        return self.message


class OneAttemptTransport(Protocol):
    def send(self, request: ProtocolHttpRequest) -> ProtocolHttpResponse:
        """Execute exactly one protocol HTTP attempt."""


def response_to_protocol_error(response: ProtocolHttpResponse) -> ProtocolError | None:
    if 200 <= response.status_code < 300:
        return None

    if response.status_code in (401, 403):
        return ProtocolError(
            error_class="AUTH_OR_SESSION_REJECTED",
            message=f"X returned HTTP {response.status_code}",
            retry_disposition=RetryDisposition.NEVER,
            status_code=response.status_code,
            scope_hint="SESSION",
        )

    if response.status_code == 404:
        return ProtocolError(
            error_class="OPERATION_NOT_FOUND",
            message="X returned HTTP 404 for the pinned operation",
            retry_disposition=RetryDisposition.NEVER,
            status_code=response.status_code,
            scope_hint="OPERATION",
        )

    if response.status_code == 429:
        retry_after = None
        if response.headers:
            header_value = response.headers.get("retry-after")
            if header_value and header_value.isdigit():
                retry_after = int(header_value)
        return ProtocolError(
            error_class="RATE_LIMITED",
            message="X returned HTTP 429",
            retry_disposition=RetryDisposition.RETRY_AFTER,
            status_code=response.status_code,
            retry_after_seconds=retry_after,
            scope_hint="SESSION",
        )

    if 500 <= response.status_code < 600:
        return ProtocolError(
            error_class="UPSTREAM_SERVER_ERROR",
            message=f"X returned HTTP {response.status_code}",
            retry_disposition=RetryDisposition.MAY_RETRY,
            status_code=response.status_code,
            scope_hint="SHARED",
        )

    return ProtocolError(
        error_class="UNEXPECTED_HTTP_STATUS",
        message=f"X returned HTTP {response.status_code}",
        retry_disposition=RetryDisposition.MAY_RETRY,
        status_code=response.status_code,
    )
