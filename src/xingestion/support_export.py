from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

from xingestion.config import AppConfig
from xingestion.errors import envelope_from_task_error
from xingestion.investigation import build_protocol_drift_package
from xingestion.releases import ReleaseStore
from xingestion.sessions import SessionStore
from xingestion.tasks import SQLiteTaskLedger
from xingestion.telemetry import ProtocolTelemetryStore
from xrev.protocol import ProtocolReleaseManifest


@dataclass(frozen=True)
class FailedTaskExportResult:
    path: Path
    package: dict[str, object]


def write_failed_task_export(
    *,
    task_id: str,
    config: AppConfig,
    manifest: ProtocolReleaseManifest,
    output_path: str | Path | None = None,
) -> FailedTaskExportResult:
    ledger = SQLiteTaskLedger(config.sqlite_path)
    package = build_failed_task_export(
        task_id=task_id,
        ledger=ledger,
        manifest=manifest,
        release_store=ReleaseStore(config.sqlite_path),
        session_store=SessionStore(config.sqlite_path),
        telemetry_store=ProtocolTelemetryStore(config.sqlite_path),
    )
    path = Path(output_path) if output_path else _default_output_path(config, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(package, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return FailedTaskExportResult(path=path, package=package)


def build_failed_task_export(
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
    if not task.error_json:
        raise ValueError(f"Task {task_id} has no error_json to export")

    drift_package = build_protocol_drift_package(
        task_id=task_id,
        ledger=ledger,
        manifest=manifest,
        release_store=release_store,
        session_store=session_store,
        telemetry_store=telemetry_store,
    )
    runtime_error = envelope_from_task_error(task.error_json)
    generated_at = datetime.now(UTC).isoformat()
    return {
        "package_type": "FAILED_TASK_SUPPORT_EXPORT",
        "generated_at": generated_at,
        "task_id": task.task_id,
        "state": task.state.value,
        "runtime_error": runtime_error.public_dict() if runtime_error else None,
        "support_summary": {
            "error_class": runtime_error.error_class if runtime_error else None,
            "severity": runtime_error.severity.value if runtime_error else "UNKNOWN",
            "scope": runtime_error.scope.value if runtime_error else "UNKNOWN",
            "operator_action": runtime_error.operator_action if runtime_error else "inspect_task",
            "raw_evidence_available": drift_package["diagnosis"]["raw_evidence_available"],
            "telemetry_attempts": drift_package["diagnosis"]["telemetry_attempts"],
            "release_health": drift_package["release"]["stored_health"],
        },
        "investigation": drift_package,
        "redaction": {
            "raw_x_secrets_included": False,
            "secret_reference_values_included": False,
            "raw_evidence_body_included": False,
            "raw_evidence_references_only": True,
        },
    }


def _default_output_path(config: AppConfig, task_id: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_task_id = _safe_name(task_id)
    return config.data_dir / "support_exports" / f"failed-task-{safe_task_id}-{stamp}.json"


def _safe_name(value: str) -> str:
    safe = "".join(char for char in value if char.isalnum() or char in {"-", "_"})
    return safe or "task"
