from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping

from xingestion.releases import ReleaseStore
from xingestion.sessions import SessionStore
from xingestion.tasks import SQLiteTaskLedger
from xingestion.telemetry import ProtocolAttempt, ProtocolTelemetryStore
from xingestion.xprotocol.protocol import ProtocolReleaseManifest


NETWORK_ROUTE_MIN_ATTEMPTS = 5
NETWORK_ROUTE_MAX_FAILURE_RATE = 0.8


def build_protocol_drift_package(
    *,
    task_id: str,
    ledger: SQLiteTaskLedger,
    manifest: ProtocolReleaseManifest,
    release_store: ReleaseStore,
    session_store: SessionStore,
    telemetry_store: ProtocolTelemetryStore,
) -> dict[str, object]:
    task = ledger.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    attempts = telemetry_store.list_for_task(task.task_id)
    session_id = _session_id_for_task(task.result_json, attempts)
    session = session_store.get_session(session_id) if session_id else None
    release = release_store.ensure_release(manifest.release_id)
    binding = _binding_for_task(manifest, task.capability_id.value, task.contract_version)
    raw_evidence = _raw_evidence_ref(task.result_json)
    error_class = _error_class(task.error_json, attempts)

    return {
        "package_type": "PROTOCOL_DRIFT_INVESTIGATION",
        "generated_at": datetime.now(UTC).isoformat(),
        "task": {
            "task_id": task.task_id,
            "state": task.state.value,
            "capability_id": task.capability_id.value,
            "contract_version": task.contract_version,
            "attempt_count": task.attempt_count,
            "max_attempts": task.max_attempts,
            "request": task.request_json,
            "plan": task.plan_json,
            "error": task.error_json,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        },
        "release": {
            "manifest_release_id": manifest.release_id,
            "manifest_status": manifest.status.value,
            "stored_health": release.health.value,
            "stored_reason": release.reason,
            "stored_updated_at": release.updated_at,
        },
        "recipe": _recipe_dict(binding.recipe) if binding else None,
        "session": _session_dict(session) if session else None,
        "telemetry_attempts": [_attempt_dict(attempt) for attempt in attempts],
        "raw_evidence": raw_evidence,
        "diagnosis": {
            "primary_error_class": error_class,
            "hints": _diagnosis_hints(error_class),
            "raw_evidence_available": raw_evidence is not None,
            "telemetry_attempts": len(attempts),
        },
    }


def build_release_risk_recommendation(
    *,
    manifest: ProtocolReleaseManifest,
    release_store: ReleaseStore,
    telemetry_store: ProtocolTelemetryStore,
) -> dict[str, object]:
    release = release_store.ensure_release(manifest.release_id)
    signals = telemetry_store.release_error_signals(manifest.release_id)
    signal_by_error = {signal.error_class: signal for signal in signals}
    network_routes = build_network_route_recommendations(
        telemetry_store=telemetry_store,
        release_id=manifest.release_id,
    )

    action = "NO_ACTION"
    severity = "LOW"
    reason = "No repeated release-level drift signal is present."
    if _signal_count(signal_by_error, "OPERATION_NOT_FOUND") >= 3:
        action = "QUARANTINE_RECOMMENDED"
        severity = "HIGH"
        reason = "Pinned GraphQL operation failures repeated for this release."
    elif _signal_count(signal_by_error, "PARSER_FAILURE") >= 3:
        action = "INVESTIGATE_RECOMMENDED"
        severity = "MEDIUM"
        reason = "Parser failures repeated for this release."
    elif _signal_count(signal_by_error, "UNEXPECTED_HTTP_STATUS") >= 5:
        action = "INVESTIGATE_RECOMMENDED"
        severity = "MEDIUM"
        reason = "Unexpected upstream statuses repeated for this release."
    elif release.health.value == "QUARANTINED":
        action = "ALREADY_QUARANTINED"
        severity = "HIGH"
        reason = "The release is already quarantined by operator state."
    elif network_routes:
        action = "NETWORK_REMEDIATION_RECOMMENDED"
        severity = _highest_route_severity(network_routes)
        reason = "One or more network routes show repeated acquisition failures."

    return {
        "release_id": manifest.release_id,
        "release_health": release.health.value,
        "action": action,
        "severity": severity,
        "reason": reason,
        "operator_action": _risk_operator_action(action),
        "signals": [
            {
                "error_class": signal.error_class,
                "count": signal.count,
                "distinct_sessions": signal.distinct_sessions,
            }
            for signal in signals
        ],
        "network_routes": network_routes,
    }


def build_network_route_recommendations(
    *,
    telemetry_store: ProtocolTelemetryStore,
    release_id: str | None = None,
    min_attempts: int = NETWORK_ROUTE_MIN_ATTEMPTS,
    max_failure_rate: float = NETWORK_ROUTE_MAX_FAILURE_RATE,
) -> list[dict[str, object]]:
    recommendations: list[dict[str, object]] = []
    for route in telemetry_store.network_summary(release_id=release_id):
        if route.network_context == "unassigned":
            continue
        if route.total_attempts < min_attempts or route.failure_rate <= max_failure_rate:
            continue
        dominant_error = _dominant_error(route.errors_by_class)
        severity = "HIGH" if route.failure_rate >= 0.95 else "MEDIUM"
        recommendations.append(
            {
                "network_context": route.network_context,
                "action": "ROTATE_OR_PAUSE_ROUTE",
                "severity": severity,
                "operator_action": _route_operator_action(dominant_error),
                "reason": _route_reason(route.network_context, dominant_error),
                "total_attempts": route.total_attempts,
                "successes": route.successes,
                "failures": route.failures,
                "failure_rate": route.failure_rate,
                "distinct_sessions": route.distinct_sessions,
                "dominant_error_class": dominant_error,
                "errors_by_class": dict(route.errors_by_class),
                "last_attempt_at": route.last_attempt_at,
                "last_success_at": route.last_success_at,
            }
        )
    return recommendations


def _binding_for_task(manifest, capability_id: str, contract_version: int):
    for binding in manifest.bindings:
        if (
            binding.capability_id.value == capability_id
            and binding.contract_version == contract_version
        ):
            return binding
    return None


def _signal_count(signal_by_error, error_class: str) -> int:
    signal = signal_by_error.get(error_class)
    return signal.count if signal else 0


def _dominant_error(errors_by_class: Mapping[str, int]) -> str | None:
    if not errors_by_class:
        return None
    return sorted(errors_by_class.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _highest_route_severity(routes: list[dict[str, object]]) -> str:
    severities = {str(route.get("severity")) for route in routes}
    if "HIGH" in severities:
        return "HIGH"
    if "MEDIUM" in severities:
        return "MEDIUM"
    return "LOW"


def _risk_operator_action(action: str) -> str:
    if action == "QUARANTINE_RECOMMENDED":
        return "quarantine_release_and_refresh_protocol_operation"
    if action == "INVESTIGATE_RECOMMENDED":
        return "investigate_release_with_raw_evidence_before_quarantine"
    if action == "ALREADY_QUARANTINED":
        return "keep_release_blocked_until_new_validation_passes"
    if action == "NETWORK_REMEDIATION_RECOMMENDED":
        return "pause_or_rotate_unhealthy_network_routes_before_changing_release"
    return "continue_monitoring"


def _route_operator_action(error_class: str | None) -> str:
    if error_class == "RATE_LIMITED":
        return "pause_route_wait_for_cooldown_or_add_healthy_session_capacity"
    if error_class == "AUTH_OR_SESSION_REJECTED":
        return "restore_or_replace_sessions_on_this_network_route"
    if error_class == "NETWORK_ERROR":
        return "check_dns_tls_proxy_or_vpn_path_for_this_route"
    if error_class == "NO_HEALTHY_SESSION":
        return "add_or_restore_healthy_sessions_for_this_route"
    if error_class:
        return "inspect_route_sessions_and_recent_raw_evidence"
    return "inspect_route_worker_logs_and_session_health"


def _route_reason(network_context: str, error_class: str | None) -> str:
    if error_class:
        return f"Route {network_context} is repeatedly failing with {error_class}."
    return f"Route {network_context} is repeatedly failing without a dominant error class."


def _recipe_dict(recipe) -> dict[str, object]:
    return {
        "revision_id": recipe.revision_id,
        "composition_hash": recipe.composition_hash,
        "status": recipe.status.value,
        "operation": {
            "revision_id": recipe.operation.revision_id,
            "operation_name": recipe.operation.operation_name,
            "operation_id": recipe.operation.operation_id,
            "content_hash": recipe.operation.content_hash,
            "operational_health": recipe.operation.operational_health,
        },
        "parser": {
            "revision_id": recipe.parser.revision_id,
            "parser_name": recipe.parser.parser_name,
            "content_hash": recipe.parser.content_hash,
            "operational_health": recipe.parser.operational_health,
        },
        "pagination": {
            "revision_id": recipe.pagination.revision_id,
            "strategy_name": recipe.pagination.strategy_name,
            "content_hash": recipe.pagination.content_hash,
            "operational_health": recipe.pagination.operational_health,
        },
        "auth_profile": {
            "revision_id": recipe.auth_profile.revision_id,
            "auth_class": recipe.auth_profile.auth_class,
            "content_hash": recipe.auth_profile.content_hash,
            "operational_health": recipe.auth_profile.operational_health,
        },
        "transaction_profile": {
            "revision_id": recipe.transaction_profile.revision_id,
            "profile_name": recipe.transaction_profile.profile_name,
            "required_headers": list(recipe.transaction_profile.required_headers),
            "content_hash": recipe.transaction_profile.content_hash,
            "operational_health": recipe.transaction_profile.operational_health,
        },
    }


def _session_dict(session) -> dict[str, object]:
    return {
        "session_id": session.session_id,
        "account_label": session.account_label,
        "network_context": session.network_context,
        "network_policy": session.network_policy.public_dict(),
        "health": session.health.value,
        "cooldown_until": session.cooldown_until,
        "attempt_count": session.attempt_count,
        "success_count": session.success_count,
        "failure_count": session.failure_count,
        "last_attempt_at": session.last_attempt_at,
        "last_success_at": session.last_success_at,
        "last_error_class": session.last_error_class,
        "last_error_message": session.last_error_message,
    }


def _attempt_dict(attempt: ProtocolAttempt) -> dict[str, object]:
    return {
        "attempt_id": attempt.attempt_id,
        "task_id": attempt.task_id,
        "capability_id": attempt.capability_id,
        "release_id": attempt.release_id,
        "recipe_revision_id": attempt.recipe_revision_id,
        "state": attempt.state,
        "session_id": attempt.session_id,
        "network_context": attempt.network_context,
        "error_class": attempt.error_class,
        "tweet_count": attempt.tweet_count,
        "next_cursor_present": attempt.next_cursor_present,
        "duration_ms": attempt.duration_ms,
        "created_at": attempt.created_at,
    }


def _session_id_for_task(
    result_json: Mapping[str, object] | None,
    attempts: tuple[ProtocolAttempt, ...],
) -> str | None:
    for attempt in reversed(attempts):
        if attempt.session_id:
            return attempt.session_id
    if result_json and isinstance(result_json.get("session"), Mapping):
        session = result_json["session"]
        value = session.get("session_id")
        return str(value) if value else None
    return None


def _raw_evidence_ref(result_json: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if not result_json or not isinstance(result_json.get("raw_evidence"), Mapping):
        return None
    raw = result_json["raw_evidence"]
    return {
        "evidence_id": raw.get("evidence_id"),
        "content_sha256": raw.get("content_sha256"),
        "storage_uri": raw.get("storage_uri"),
    }


def _error_class(
    error_json: Mapping[str, object] | None,
    attempts: tuple[ProtocolAttempt, ...],
) -> str | None:
    if error_json and error_json.get("error_class"):
        return str(error_json["error_class"])
    for attempt in reversed(attempts):
        if attempt.error_class:
            return attempt.error_class
    return None


def _diagnosis_hints(error_class: str | None) -> list[str]:
    if error_class == "OPERATION_NOT_FOUND":
        return [
            "Pinned X GraphQL operation may be stale.",
            "Quarantine the release if failures repeat across sessions.",
            "Refresh the operation id and candidate protocol release from live evidence.",
        ]
    if error_class == "AUTH_OR_SESSION_REJECTED":
        return [
            "Session auth was rejected by X.",
            "Rotate or restore the affected session after validating auth material.",
        ]
    if error_class == "RATE_LIMITED":
        return [
            "Session hit a rate limit.",
            "Wait for cooldown or add healthy sessions before retrying at volume.",
        ]
    if error_class == "PROTOCOL_RELEASE_BLOCKED":
        return [
            "The current release was intentionally blocked by operator health state.",
            "Reactivate the release only after investigation.",
        ]
    if error_class:
        return [
            "Review task error, telemetry attempt, and release recipe metadata together.",
            "Compare failures across sessions before changing protocol code.",
        ]
    return ["No protocol error class is recorded for this task."]
