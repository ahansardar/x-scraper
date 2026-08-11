from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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


@dataclass(frozen=True)
class SupportExportSummary:
    path: Path
    name: str
    size_bytes: int
    modified_at: str
    package_type: str
    task_id: str | None
    state: str | None
    generated_at: str | None
    error_class: str | None
    severity: str | None
    redacted: bool
    readable: bool
    parse_error: str | None = None

    def public_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "name": self.name,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "package_type": self.package_type,
            "task_id": self.task_id,
            "state": self.state,
            "generated_at": self.generated_at,
            "error_class": self.error_class,
            "severity": self.severity,
            "redacted": self.redacted,
            "readable": self.readable,
            "parse_error": self.parse_error,
        }


@dataclass(frozen=True)
class SupportExportRetentionResult:
    export_dir: Path
    cutoff: str
    matched_exports: int
    deleted_exports: int
    dry_run: bool
    exports: tuple[SupportExportSummary, ...]

    def public_dict(self) -> dict[str, object]:
        return {
            "export_dir": str(self.export_dir),
            "cutoff": self.cutoff,
            "matched_exports": self.matched_exports,
            "deleted_exports": self.deleted_exports,
            "dry_run": self.dry_run,
            "exports": [item.public_dict() for item in self.exports],
        }


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


def list_support_exports(
    config: AppConfig,
    *,
    limit: int = 25,
) -> list[SupportExportSummary]:
    export_dir = support_export_dir(config)
    if not export_dir.exists():
        return []
    summaries = [_summarize_export(path) for path in export_dir.glob("failed-task-*.json")]
    summaries.sort(key=lambda item: item.modified_at, reverse=True)
    return summaries[:limit]


def read_support_export(config: AppConfig, name: str) -> dict[str, object]:
    path = support_export_file(config, name)
    summary = _summarize_export(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "summary": summary.public_dict(),
        "package": payload,
    }


def support_export_file(config: AppConfig, name: str) -> Path:
    path = _support_export_path(config, name)
    if not path.exists():
        raise ValueError(f"Support export {name} not found")
    summary = _summarize_export(path)
    if not summary.readable:
        raise ValueError(f"Support export {name} is not readable JSON")
    return path


def apply_support_export_retention(
    config: AppConfig,
    *,
    days: int,
    dry_run: bool,
) -> SupportExportRetentionResult:
    if days < 1:
        raise ValueError("support export retention days must be at least 1")
    export_dir = support_export_dir(config)
    cutoff_dt = datetime.now(UTC) - timedelta(days=days)
    cutoff = cutoff_dt.isoformat()
    if not export_dir.exists():
        return SupportExportRetentionResult(
            export_dir=export_dir,
            cutoff=cutoff,
            matched_exports=0,
            deleted_exports=0,
            dry_run=dry_run,
            exports=(),
        )

    matched: list[SupportExportSummary] = []
    deleted = 0
    for path in export_dir.glob("failed-task-*.json"):
        stat = path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
        if modified_at >= cutoff_dt:
            continue
        summary = _summarize_export(path)
        matched.append(summary)
        if not dry_run:
            path.unlink()
            deleted += 1

    matched.sort(key=lambda item: item.modified_at)
    return SupportExportRetentionResult(
        export_dir=export_dir,
        cutoff=cutoff,
        matched_exports=len(matched),
        deleted_exports=deleted,
        dry_run=dry_run,
        exports=tuple(matched),
    )


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
    return support_export_dir(config) / f"failed-task-{safe_task_id}-{stamp}.json"


def support_export_dir(config: AppConfig) -> Path:
    return config.data_dir / "support_exports"


def _support_export_path(config: AppConfig, name: str) -> Path:
    if Path(name).name != name:
        raise ValueError("Support export name must be a file name")
    if not name.startswith("failed-task-") or not name.endswith(".json"):
        raise ValueError("Support export name must match failed-task-*.json")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if any(char not in allowed for char in name):
        raise ValueError("Support export name contains unsupported characters")
    return support_export_dir(config) / name


def _summarize_export(path: Path) -> SupportExportSummary:
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
    base = {
        "path": path,
        "name": path.name,
        "size_bytes": stat.st_size,
        "modified_at": modified_at,
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return SupportExportSummary(
            **base,
            package_type="UNKNOWN",
            task_id=None,
            state=None,
            generated_at=None,
            error_class=None,
            severity=None,
            redacted=False,
            readable=False,
            parse_error=str(exc),
        )
    if not isinstance(payload, dict):
        return SupportExportSummary(
            **base,
            package_type="UNKNOWN",
            task_id=None,
            state=None,
            generated_at=None,
            error_class=None,
            severity=None,
            redacted=False,
            readable=False,
            parse_error="support export root is not an object",
        )

    summary = payload.get("support_summary")
    redaction = payload.get("redaction")
    return SupportExportSummary(
        **base,
        package_type=str(payload.get("package_type") or "UNKNOWN"),
        task_id=payload.get("task_id"),
        state=payload.get("state"),
        generated_at=payload.get("generated_at"),
        error_class=summary.get("error_class") if isinstance(summary, dict) else None,
        severity=summary.get("severity") if isinstance(summary, dict) else None,
        redacted=(
            isinstance(redaction, dict)
            and redaction.get("raw_x_secrets_included") is False
            and redaction.get("raw_evidence_body_included") is False
        ),
        readable=True,
        parse_error=None,
    )


def _safe_name(value: str) -> str:
    safe = "".join(char for char in value if char.isalnum() or char in {"-", "_"})
    return safe or "task"
