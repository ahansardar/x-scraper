from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class ErrorSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ErrorScope(StrEnum):
    TASK = "TASK"
    SESSION = "SESSION"
    PROTOCOL = "PROTOCOL"
    RELEASE = "RELEASE"
    STORAGE = "STORAGE"
    TRANSPORT = "TRANSPORT"
    OPERATOR = "OPERATOR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ErrorProfile:
    error_class: str
    severity: ErrorSeverity
    scope: ErrorScope
    operator_action: str
    retryable: bool


@dataclass(frozen=True)
class RuntimeErrorEnvelope:
    error_class: str
    message: str
    severity: ErrorSeverity
    scope: ErrorScope
    operator_action: str
    retryable: bool
    retry_disposition: str | None = None
    status_code: int | None = None
    retry_after_seconds: int | None = None

    def public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "error_class": self.error_class,
            "message": self.message,
            "severity": self.severity.value,
            "scope": self.scope.value,
            "operator_action": self.operator_action,
            "retryable": self.retryable,
        }
        if self.retry_disposition is not None:
            payload["retry_disposition"] = self.retry_disposition
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        if self.retry_after_seconds is not None:
            payload["retry_after_seconds"] = self.retry_after_seconds
        return payload

    def log_fields(self) -> dict[str, object]:
        return {
            "error_class": self.error_class,
            "severity": self.severity.value,
            "scope": self.scope.value,
            "operator_action": self.operator_action,
            "retryable": self.retryable,
            "status_code": self.status_code,
            "retry_after_seconds": self.retry_after_seconds,
        }


ERROR_PROFILES: dict[str, ErrorProfile] = {
    "AUTH_OR_SESSION_REJECTED": ErrorProfile(
        error_class="AUTH_OR_SESSION_REJECTED",
        severity=ErrorSeverity.HIGH,
        scope=ErrorScope.SESSION,
        operator_action="restore_or_replace_x_session_credentials",
        retryable=False,
    ),
    "RATE_LIMITED": ErrorProfile(
        error_class="RATE_LIMITED",
        severity=ErrorSeverity.MEDIUM,
        scope=ErrorScope.SESSION,
        operator_action="wait_for_cooldown_or_rotate_healthy_session",
        retryable=True,
    ),
    "OPERATION_NOT_FOUND": ErrorProfile(
        error_class="OPERATION_NOT_FOUND",
        severity=ErrorSeverity.CRITICAL,
        scope=ErrorScope.PROTOCOL,
        operator_action="investigate_protocol_release_and_consider_quarantine",
        retryable=False,
    ),
    "PROTOCOL_RELEASE_BLOCKED": ErrorProfile(
        error_class="PROTOCOL_RELEASE_BLOCKED",
        severity=ErrorSeverity.HIGH,
        scope=ErrorScope.RELEASE,
        operator_action="activate_release_after_investigation_or_publish_new_release",
        retryable=False,
    ),
    "SESSION_UNAVAILABLE": ErrorProfile(
        error_class="SESSION_UNAVAILABLE",
        severity=ErrorSeverity.HIGH,
        scope=ErrorScope.SESSION,
        operator_action="restore_or_add_a_healthy_session",
        retryable=True,
    ),
    "UPSTREAM_SERVER_ERROR": ErrorProfile(
        error_class="UPSTREAM_SERVER_ERROR",
        severity=ErrorSeverity.MEDIUM,
        scope=ErrorScope.TRANSPORT,
        operator_action="monitor_retries_and_check_x_availability",
        retryable=True,
    ),
    "TRANSPORT_ERROR": ErrorProfile(
        error_class="TRANSPORT_ERROR",
        severity=ErrorSeverity.MEDIUM,
        scope=ErrorScope.TRANSPORT,
        operator_action="check_network_dns_tls_and_proxy_path",
        retryable=True,
    ),
    "UNEXPECTED_HTTP_STATUS": ErrorProfile(
        error_class="UNEXPECTED_HTTP_STATUS",
        severity=ErrorSeverity.MEDIUM,
        scope=ErrorScope.TRANSPORT,
        operator_action="inspect_raw_evidence_and_protocol_response",
        retryable=True,
    ),
    "TASK_NOT_FOUND": ErrorProfile(
        error_class="TASK_NOT_FOUND",
        severity=ErrorSeverity.HIGH,
        scope=ErrorScope.STORAGE,
        operator_action="inspect_sqlite_task_ledger_integrity",
        retryable=False,
    ),
    "OBJECT_NOT_FOUND": ErrorProfile(
        error_class="OBJECT_NOT_FOUND",
        severity=ErrorSeverity.LOW,
        scope=ErrorScope.PROTOCOL,
        operator_action="no_action_object_does_not_exist_or_was_deleted",
        retryable=False,
    ),
    "ACCESS_NOT_AUTHORIZED": ErrorProfile(
        error_class="ACCESS_NOT_AUTHORIZED",
        severity=ErrorSeverity.LOW,
        scope=ErrorScope.PROTOCOL,
        operator_action="no_action_object_is_protected_or_access_restricted",
        retryable=False,
    ),
    "ValueError": ErrorProfile(
        error_class="ValueError",
        severity=ErrorSeverity.HIGH,
        scope=ErrorScope.TASK,
        operator_action="inspect_task_payload_and_planner_contract",
        retryable=False,
    ),
}


def classify_error(
    error_class: str,
    *,
    message: str,
    retry_disposition: object | None = None,
    status_code: int | None = None,
    retry_after_seconds: int | None = None,
    scope_hint: str | None = None,
) -> RuntimeErrorEnvelope:
    profile = ERROR_PROFILES.get(error_class) or _fallback_profile(error_class, scope_hint)
    retry_disposition_value = str(retry_disposition) if retry_disposition is not None else None
    return RuntimeErrorEnvelope(
        error_class=error_class,
        message=message,
        severity=profile.severity,
        scope=_scope_from_hint(scope_hint) or profile.scope,
        operator_action=profile.operator_action,
        retryable=profile.retryable,
        retry_disposition=retry_disposition_value,
        status_code=status_code,
        retry_after_seconds=retry_after_seconds,
    )


def classify_exception(exc: BaseException) -> RuntimeErrorEnvelope:
    error_class = str(getattr(exc, "error_class", exc.__class__.__name__))
    return classify_error(
        error_class,
        message=str(exc),
        retry_disposition=getattr(exc, "retry_disposition", None),
        status_code=getattr(exc, "status_code", None),
        retry_after_seconds=getattr(exc, "retry_after_seconds", None),
        scope_hint=getattr(exc, "scope_hint", None),
    )


def envelope_from_task_error(error_json: Mapping[str, object] | None) -> RuntimeErrorEnvelope | None:
    if not error_json:
        return None
    nested = error_json.get("runtime_error")
    if isinstance(nested, Mapping):
        return _envelope_from_mapping(nested)
    error_class = str(error_json.get("error_class") or "UNKNOWN")
    return classify_error(
        error_class,
        message=str(error_json.get("message") or ""),
        retry_disposition=error_json.get("retry_disposition"),
        retry_after_seconds=_optional_int(error_json.get("retry_after_seconds")),
    )


def _envelope_from_mapping(payload: Mapping[str, object]) -> RuntimeErrorEnvelope:
    return RuntimeErrorEnvelope(
        error_class=str(payload.get("error_class") or "UNKNOWN"),
        message=str(payload.get("message") or ""),
        severity=ErrorSeverity(str(payload.get("severity") or ErrorSeverity.MEDIUM.value)),
        scope=ErrorScope(str(payload.get("scope") or ErrorScope.UNKNOWN.value)),
        operator_action=str(payload.get("operator_action") or "inspect_task_and_logs"),
        retryable=bool(payload.get("retryable")),
        retry_disposition=(
            str(payload["retry_disposition"])
            if payload.get("retry_disposition") is not None
            else None
        ),
        status_code=_optional_int(payload.get("status_code")),
        retry_after_seconds=_optional_int(payload.get("retry_after_seconds")),
    )


def _fallback_profile(error_class: str, scope_hint: str | None) -> ErrorProfile:
    return ErrorProfile(
        error_class=error_class,
        severity=ErrorSeverity.MEDIUM,
        scope=_scope_from_hint(scope_hint) or ErrorScope.UNKNOWN,
        operator_action="inspect_task_error_logs_and_raw_evidence",
        retryable=False,
    )


def _scope_from_hint(scope_hint: str | None) -> ErrorScope | None:
    if not scope_hint:
        return None
    normalized = scope_hint.upper()
    if normalized == "OPERATION":
        return ErrorScope.PROTOCOL
    if normalized in ErrorScope.__members__:
        return ErrorScope[normalized]
    return None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
