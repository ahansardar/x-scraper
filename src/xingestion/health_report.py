from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Callable

from psycopg_pool import ConnectionPool
import redis

from xingestion.canonical import CanonicalStore
from xingestion.config import AppConfig
from xingestion.dispatch import redis_queue_stats
from xingestion.errors import RuntimeErrorEnvelope, envelope_from_task_error
from xingestion.investigation import (
    build_network_route_recommendations,
    build_release_risk_recommendation,
)
from xingestion.migrations import MigrationRunner
from xingestion.preflight import DeploymentPreflight, PreflightCheck
from xingestion.releases import ReleaseRecord, ReleaseStore
from xingestion.secrets import secret_provider_status
from xingestion.sessions import SessionRecord, SessionStore
from xingestion.tasks import CapabilityTask, PostgresTaskLedger
from xingestion.telemetry import NetworkTelemetrySummary, ProtocolTelemetryStore, TelemetrySummary
from xingestion.xprotocol.protocol import ProtocolReleaseManifest
from xingestion.xprotocol.runtime import WebSessionAuth


@dataclass(frozen=True)
class HealthReportResult:
    ok: bool
    path: Path
    report: dict[str, object]


def write_health_report(
    *,
    config: AppConfig,
    migration_runner: MigrationRunner,
    manifest: ProtocolReleaseManifest,
    auth: WebSessionAuth,
    base_url: str | None = None,
    output_path: str | Path | None = None,
) -> HealthReportResult:
    report = build_health_report(
        config=config,
        migration_runner=migration_runner,
        manifest=manifest,
        auth=auth,
        base_url=base_url,
    )
    path = Path(output_path) if output_path else _default_output_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return HealthReportResult(ok=bool(report["ok"]), path=path, report=report)


def build_health_report(
    *,
    config: AppConfig,
    migration_runner: MigrationRunner,
    manifest: ProtocolReleaseManifest,
    auth: WebSessionAuth,
    base_url: str | None = None,
) -> dict[str, object]:
    generated_at = datetime.now(UTC).isoformat()
    preflight = DeploymentPreflight(
        config=config,
        migration_runner=migration_runner,
        manifest=manifest,
        auth=auth,
        base_url=base_url,
    ).run()
    release_store = ReleaseStore(config.sqlite_path)
    telemetry_store = ProtocolTelemetryStore(config.sqlite_path)

    return {
        "report_type": "XINGESTION_HEALTH_REPORT",
        "generated_at": generated_at,
        "ok": preflight.ok,
        "base_url": base_url,
        "config": _config_dict(config),
        "storage": _storage_dict(config),
        "startup": _startup_dict(preflight.checks),
        "preflight": [_preflight_check_dict(check) for check in preflight.checks],
        "migrations": _safe_section(lambda: _migration_status_dict(migration_runner)),
        "tasks": _safe_section(lambda: _task_dict(config)),
        "redis_queue": _safe_section(lambda: _redis_queue_dict(config)),
        "runtime_errors": _safe_section(lambda: _runtime_errors_dict(config)),
        "canonical": _safe_section(lambda: CanonicalStore(config.sqlite_path).counts()),
        "telemetry": _safe_section(lambda: _telemetry_summary_dict(telemetry_store.summary())),
        "network_health": _safe_section(
            lambda: _network_health_dict(config, manifest.release_id, telemetry_store)
        ),
        "release": _safe_section(lambda: _release_dict(release_store.ensure_release(manifest.release_id))),
        "release_risk": _safe_section(
            lambda: build_release_risk_recommendation(
                manifest=manifest,
                release_store=release_store,
                telemetry_store=telemetry_store,
            )
        ),
        "sessions": _safe_section(lambda: _sessions_dict(SessionStore(config.sqlite_path))),
    }


def _config_dict(config: AppConfig) -> dict[str, object]:
    return {
        "data_dir": str(config.data_dir),
        "sqlite_path": str(config.sqlite_path),
        "raw_evidence_dir": str(config.raw_evidence_dir),
        "host": config.host,
        "port": config.port,
        "retention_days": config.retention_days,
        "default_session_id": config.default_session_id,
        "default_account_label": config.default_account_label,
        "default_network_context": config.default_network_context,
        "worker_network_context": config.worker_network_context or None,
        "operator_auth_required": False,
        "secret_backend": _safe_secret_backend_dict(config),
        "require_migrations": config.require_migrations,
        "max_active_tasks_per_capability": config.max_active_tasks_per_capability,
    }


def _redact_dsn(dsn: str) -> str:
    if "@" not in dsn or "://" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    credentials, _, host_part = rest.partition("@")
    user = credentials.split(":", 1)[0] if credentials else ""
    return f"{scheme}://{user}:***@{host_part}"


def _storage_dict(config: AppConfig) -> dict[str, object]:
    return {
        "data_dir": str(config.data_dir),
        "data_dir_exists": config.data_dir.exists(),
        "sqlite_path": str(config.sqlite_path),
        "sqlite_exists": config.sqlite_path.exists(),
        "postgres_dsn": _redact_dsn(config.postgres_dsn),
        "redis_url": config.redis_url,
        "raw_evidence_dir": str(config.raw_evidence_dir),
        "raw_evidence_dir_exists": config.raw_evidence_dir.exists(),
        "reports_dir": str(config.data_dir / "reports"),
        "protocol_validation_dir": str(config.data_dir / "protocol_validation"),
    }


def _safe_secret_backend_dict(config: AppConfig) -> dict[str, object]:
    try:
        return secret_provider_status(config).public_dict()
    except ValueError as exc:
        return {
            "provider": config.secret_provider,
            "configured": False,
            "reference_scheme": (
                config.default_credential_ref.split(":", 1)[0]
                if ":" in config.default_credential_ref
                else "unknown"
            ),
            "reference_configured": bool(config.default_credential_ref),
            "missing_fields": [],
            "message": str(exc),
        }


def _preflight_check_dict(check: PreflightCheck) -> dict[str, str]:
    return {
        "name": check.name,
        "status": check.status,
        "message": check.message,
    }


def _startup_dict(checks: tuple[PreflightCheck, ...]) -> dict[str, object]:
    startup = next(
        (check for check in checks if check.name == "startup_directories"),
        PreflightCheck("startup_directories", "FAIL", "startup directory check missing"),
    )
    return {
        "ok": startup.status != "FAIL",
        "status": startup.status,
        "message": startup.message,
    }


def _migration_status_dict(runner: MigrationRunner) -> dict[str, object]:
    status = runner.status()
    return {
        "available_versions": list(status.available_versions),
        "applied_versions": list(status.applied_versions),
        "pending_versions": list(status.pending_versions),
        "current": status.current,
    }


def _open_task_ledger(config: AppConfig) -> PostgresTaskLedger:
    pool = ConnectionPool(config.postgres_dsn, min_size=1, max_size=1, open=True)
    return PostgresTaskLedger(pool)


def _task_dict(config: AppConfig) -> dict[str, object]:
    ledger = _open_task_ledger(config)
    counts = ledger.task_state_counts()
    active_states = ("CREATED", "ENQUEUED", "RUNNING", "RETRY_SCHEDULED")
    terminal_states = ("DONE", "DEAD_LETTER", "CANCELLED")
    return {
        "state_counts": counts,
        "active_total": sum(int(counts[state]) for state in active_states),
        "terminal_total": sum(int(counts[state]) for state in terminal_states),
        "outbox": ledger.outbox_stats(),
    }


def _redis_queue_dict(config: AppConfig) -> dict[str, object]:
    client = redis.Redis.from_url(config.redis_url, decode_responses=True)
    try:
        return redis_queue_stats(
            client,
            stream_key=config.redis_stream_key,
            group_name=config.redis_consumer_group,
        )
    finally:
        client.close()


def _runtime_errors_dict(config: AppConfig) -> dict[str, object]:
    ledger = _open_task_ledger(config)
    tasks = ledger.list_recent_task_errors(limit=25)

    envelopes: list[tuple[CapabilityTask, RuntimeErrorEnvelope]] = []
    for task in tasks:
        error_json = task.error_json or {
            "error_class": "INVALID_ERROR_JSON",
            "message": "Task error_json could not be decoded",
        }
        envelope = envelope_from_task_error(error_json)
        if envelope is not None:
            envelopes.append((task, envelope))

    return {
        "total": len(envelopes),
        "by_class": _count_by(envelopes, lambda envelope: envelope.error_class),
        "by_severity": _count_by(envelopes, lambda envelope: envelope.severity.value),
        "by_scope": _count_by(envelopes, lambda envelope: envelope.scope.value),
        "recent": [
            {
                "task_id": task.task_id,
                "state": task.state.value,
                "updated_at": task.updated_at,
                "runtime_error": envelope.public_dict(),
            }
            for task, envelope in envelopes[:10]
        ],
    }


def _telemetry_summary_dict(summary: TelemetrySummary) -> dict[str, object]:
    return {
        "total_attempts": summary.total_attempts,
        "successes": summary.successes,
        "failures": summary.failures,
        "errors_by_class": dict(summary.errors_by_class),
    }


def _network_health_dict(
    config: AppConfig,
    release_id: str,
    telemetry_store: ProtocolTelemetryStore,
) -> dict[str, object]:
    route_recommendations = {
        item["network_context"]: item
        for item in build_network_route_recommendations(
            telemetry_store=telemetry_store,
            release_id=release_id,
        )
    }
    return {
        "release_id": release_id,
        "worker_network_context": config.worker_network_context or None,
        "routes": [
            _network_route_dict(route, route_recommendations.get(route.network_context))
            for route in telemetry_store.network_summary(release_id=release_id)
        ],
        "recommendations": list(route_recommendations.values()),
    }


def _network_route_dict(
    route: NetworkTelemetrySummary,
    recommendation: dict[str, object] | None = None,
) -> dict[str, object]:
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
        "recommendation": recommendation,
    }


def _release_dict(release: ReleaseRecord) -> dict[str, object]:
    return {
        "release_id": release.release_id,
        "health": release.health.value,
        "reason": release.reason,
        "updated_at": release.updated_at,
    }


def _sessions_dict(store: SessionStore) -> dict[str, object]:
    sessions = store.list_sessions()
    return {
        "total": len(sessions),
        "by_health": _session_health_counts(sessions),
        "sessions": [_session_dict(session) for session in sessions],
    }


def _session_dict(session: SessionRecord) -> dict[str, object]:
    return {
        "session_id": session.session_id,
        "account_label": session.account_label,
        "network_context": session.network_context,
        "network_policy": session.network_policy.public_dict(),
        "health": session.health.value,
        "lease_owner": session.lease_owner,
        "lease_expires_at": session.lease_expires_at,
        "cooldown_until": session.cooldown_until,
        "attempt_count": session.attempt_count,
        "success_count": session.success_count,
        "failure_count": session.failure_count,
        "last_attempt_at": session.last_attempt_at,
        "last_success_at": session.last_success_at,
        "last_error_class": session.last_error_class,
        "last_error_message": session.last_error_message,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _session_health_counts(sessions: tuple[SessionRecord, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for session in sessions:
        counts[session.health.value] = counts.get(session.health.value, 0) + 1
    return counts


def _count_by(
    rows: list[tuple[CapabilityTask, RuntimeErrorEnvelope]],
    key_fn: Callable[[RuntimeErrorEnvelope], str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, envelope in rows:
        key = key_fn(envelope)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _safe_section(loader: Callable[[], object]) -> object:
    try:
        return loader()
    except Exception as exc:
        return {
            "error": exc.__class__.__name__,
            "message": str(exc),
        }


def _default_output_path(config: AppConfig) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return config.data_dir / "reports" / f"health-report-{stamp}.json"
