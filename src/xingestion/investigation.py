from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping

from xingestion.pagination_chain import is_pagination_error_class, walk_pagination_chain
from xingestion.releases import RecipeValidationStore, ReleaseStore, recipe_validation_freshness
from xingestion.sessions import SessionStore
from xingestion.sessions.network import network_matches
from xingestion.tasks import TaskLedger
from xingestion.telemetry import ProtocolAttempt, ProtocolTelemetryStore
from xingestion.xprotocol.protocol import ProtocolReleaseManifest


NETWORK_ROUTE_MIN_ATTEMPTS = 5
NETWORK_ROUTE_MAX_FAILURE_RATE = 0.8
DRIFT_WINDOW_SIZE = 20
DRIFT_RECENT_FAILURE_RATE_THRESHOLD = 0.4
DRIFT_HARD_SIGNAL_ERROR_CLASSES = ("OPERATION_NOT_FOUND", "PARSER_FAILURE")


def build_protocol_drift_package(
    *,
    task_id: str,
    ledger: TaskLedger,
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
    pagination_chain = walk_pagination_chain(ledger, task)

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
        "pagination_chain": {
            "is_pagination_failure": is_pagination_error_class(error_class),
            "root_task_id": pagination_chain[0].task_id if pagination_chain else None,
            "chain_length": len(pagination_chain),
            "pages": [entry.public_dict() for entry in pagination_chain],
        },
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


def build_search_route_monitoring(
    *,
    manifest: ProtocolReleaseManifest,
    release_store: ReleaseStore,
    telemetry_store: ProtocolTelemetryStore,
    network_context: str | None = None,
) -> dict[str, object]:
    release = release_store.ensure_release(manifest.release_id)
    release_risk = build_release_risk_recommendation(
        manifest=manifest,
        release_store=release_store,
        telemetry_store=telemetry_store,
    )
    target_network_context = (network_context or "direct").strip() or "direct"
    route_summaries = telemetry_store.network_summary(release_id=manifest.release_id)
    route_recommendations = build_network_route_recommendations(
        telemetry_store=telemetry_store,
        release_id=manifest.release_id,
    )
    matching_route = next(
        (
            route
            for route in route_summaries
            if network_matches(route.network_context, target_network_context)
        ),
        None,
    )
    matching_recommendation = next(
        (
            recommendation
            for recommendation in route_recommendations
            if network_matches(
                str(recommendation.get("network_context") or "direct"),
                target_network_context,
            )
        ),
        None,
    )

    if release.health.value in {"QUARANTINED", "RETIRED"}:
        action = "RELEASE_BLOCKED"
        severity = "HIGH"
        reason = f"release={manifest.release_id} health={release.health.value} execution blocked"
        operator_action = "keep_release_blocked_until_new_validation_passes"
    elif release_risk["action"] == "QUARANTINE_RECOMMENDED":
        action = str(release_risk["action"])
        severity = str(release_risk["severity"])
        reason = str(release_risk["reason"])
        operator_action = str(release_risk["operator_action"])
    elif matching_recommendation is not None:
        action = str(matching_recommendation["action"])
        severity = str(matching_recommendation["severity"])
        reason = str(matching_recommendation["reason"])
        operator_action = str(matching_recommendation["operator_action"])
    elif matching_route is None:
        action = "NO_ROUTE_DATA"
        severity = "LOW"
        reason = (
            f"No telemetry has been recorded yet for network_context={target_network_context}."
        )
        operator_action = "continue_monitoring"
    else:
        action = "CONTINUE_MONITORING"
        severity = "LOW"
        reason = (
            f"Route {target_network_context} remains within the approved search-route thresholds."
        )
        operator_action = "continue_monitoring"

    return {
        "release_id": manifest.release_id,
        "release_health": release.health.value,
        "network_context": target_network_context,
        "matched_network_context": matching_route.network_context if matching_route else None,
        "has_route_data": matching_route is not None,
        "route_summary": _network_summary_dict(matching_route) if matching_route else None,
        "route_recommendation": matching_recommendation,
        "release_risk_action": release_risk["action"],
        "action": action,
        "severity": severity,
        "reason": reason,
        "operator_action": operator_action,
    }


def build_protocol_drift_report(
    *,
    manifest: ProtocolReleaseManifest,
    release_store: ReleaseStore,
    telemetry_store: ProtocolTelemetryStore,
    validation_store: RecipeValidationStore,
    window: int = DRIFT_WINDOW_SIZE,
) -> dict[str, object]:
    """Is the approved recipe drifting in *live production* right now.

    Complements build_release_risk_recommendation(), which scores lifetime-
    cumulative error counts and never resets -- a release with a handful of
    failures months ago stays flagged forever, and a release that just
    started failing is diluted by a long healthy history. This looks only
    at the most recent `window` attempts against the *currently* approved
    recipe (not stale ones from a prior recipe rotation under the same
    release), so "this used to work and just stopped" is detectable.
    """
    release = release_store.ensure_release(manifest.release_id)
    binding = manifest.bindings[0] if manifest.bindings else None
    recipe_revision_id = binding.recipe.revision_id if binding else None
    composition_hash = binding.recipe.composition_hash if binding else None

    recent = (
        telemetry_store.recent_attempts(
            manifest.release_id, recipe_revision_id=recipe_revision_id, limit=window
        )
        if recipe_revision_id is not None
        else ()
    )
    attempts_in_window = len(recent)
    failures_in_window = sum(1 for attempt in recent if attempt.state == "FAILURE")
    failure_rate = (failures_in_window / attempts_in_window) if attempts_in_window else 0.0

    signal_counts: dict[str, int] = {}
    for attempt in recent:
        if attempt.error_class:
            signal_counts[attempt.error_class] = signal_counts.get(attempt.error_class, 0) + 1

    last_success_at = next((a.created_at for a in recent if a.state == "SUCCESS"), None)
    last_failure_at = next((a.created_at for a in recent if a.state == "FAILURE"), None)

    recipe_fresh = None
    if recipe_revision_id is not None:
        freshness = recipe_validation_freshness(store=validation_store, manifest=manifest)
        recipe_fresh = all(entry.fresh for entry in freshness) if freshness else None

    hard_signal = next(
        (cls for cls in DRIFT_HARD_SIGNAL_ERROR_CLASSES if signal_counts.get(cls, 0) > 0),
        None,
    )

    drifting = False
    severity = "LOW"
    if attempts_in_window == 0:
        reason = "No recent telemetry attempts for the approved recipe."
    elif hard_signal is not None:
        drifting = True
        severity = "HIGH"
        reason = (
            f"{hard_signal} appeared {signal_counts[hard_signal]} time(s) in the last "
            f"{attempts_in_window} attempts -- the approved recipe is failing against "
            "live X responses."
        )
    elif failure_rate >= DRIFT_RECENT_FAILURE_RATE_THRESHOLD:
        drifting = True
        severity = "MEDIUM"
        reason = (
            f"{failures_in_window}/{attempts_in_window} recent attempts failed "
            f"({failure_rate:.0%}), at or above the drift threshold of "
            f"{DRIFT_RECENT_FAILURE_RATE_THRESHOLD:.0%}."
        )
    elif recipe_fresh is False:
        drifting = True
        severity = "MEDIUM"
        reason = "The approved recipe's live composition has no fresh, passing validation record."
    else:
        reason = "No recent drift signal in the last window of attempts."

    return {
        "release_id": manifest.release_id,
        "release_health": release.health.value,
        "recipe_revision_id": recipe_revision_id,
        "composition_hash": composition_hash,
        "window_size": window,
        "attempts_in_window": attempts_in_window,
        "failures_in_window": failures_in_window,
        "failure_rate": failure_rate,
        "signals": [
            {"error_class": error_class, "count": count}
            for error_class, count in sorted(
                signal_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "last_success_at": last_success_at,
        "last_failure_at": last_failure_at,
        "recipe_fresh": recipe_fresh,
        "drifting": drifting,
        "severity": severity,
        "reason": reason,
        "operator_action": _drift_operator_action(drifting, hard_signal),
    }


def _drift_operator_action(drifting: bool, hard_signal: str | None) -> str:
    if hard_signal == "OPERATION_NOT_FOUND":
        return "quarantine_release_and_refresh_protocol_operation"
    if hard_signal == "PARSER_FAILURE":
        return "investigate_release_with_raw_evidence_before_quarantine"
    if drifting:
        return "investigate_recent_failures_and_consider_fresh_validation_run"
    return "continue_monitoring"


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


def _network_summary_dict(route) -> dict[str, object]:
    return {
        "network_context": route.network_context,
        "total_attempts": route.total_attempts,
        "successes": route.successes,
        "failures": route.failures,
        "failure_rate": route.failure_rate,
        "distinct_sessions": route.distinct_sessions,
        "last_attempt_at": route.last_attempt_at,
        "last_success_at": route.last_success_at,
        "errors_by_class": dict(route.errors_by_class),
    }


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
    if is_pagination_error_class(error_class):
        return [
            "See pagination_chain for the cursor sequence across every page fetched before this failure.",
            "PAGINATION_CURSOR_LOOP means X returned a cursor already used earlier in this chain; "
            "PAGINATION_CURSOR_MISSING/PAGINATION_EMPTY_CONTINUATION mean X stopped returning a usable "
            "continuation cursor.",
            "If this repeats across sessions or queries, the pagination strategy may need re-validation "
            "against a fresh capture.",
        ]
    if error_class:
        return [
            "Review task error, telemetry attempt, and release recipe metadata together.",
            "Compare failures across sessions before changing protocol code.",
        ]
    return ["No protocol error class is recorded for this task."]
