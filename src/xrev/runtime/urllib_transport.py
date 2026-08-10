from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .transport import (
    OneAttemptTransport,
    ProtocolError,
    ProtocolHttpRequest,
    ProtocolHttpResponse,
    RetryDisposition,
)


class UrllibJsonTransport:
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def send(self, request: ProtocolHttpRequest) -> ProtocolHttpResponse:
        encoded = json.dumps(request.json_body).encode("utf-8")
        urllib_request = Request(
            request.url,
            data=encoded,
            headers=dict(request.headers),
            method=request.method,
        )

        try:
            with urlopen(urllib_request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                return ProtocolHttpResponse(
                    status_code=response.status,
                    json_body=json.loads(body) if body else {},
                    headers={key.lower(): value for key, value in response.headers.items()},
                )
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return ProtocolHttpResponse(
                status_code=exc.code,
                json_body=_json_or_error(body),
                headers={key.lower(): value for key, value in exc.headers.items()},
            )
        except URLError as exc:
            raise ProtocolError(
                error_class="TRANSPORT_ERROR",
                message=str(exc.reason),
                retry_disposition=RetryDisposition.MAY_RETRY,
                scope_hint="SHARED",
            ) from exc


def _json_or_error(body: str):
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw_error": body[:2000]}
