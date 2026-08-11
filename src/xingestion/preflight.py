from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from urllib import request

from xingestion.config import AppConfig
from xingestion.investigation import build_release_risk_recommendation
from xingestion.logging_config import load_logging_settings
from xingestion.migrations import MigrationRunner
from xingestion.releases import ReleaseHealth, ReleaseStore
from xingestion.secrets import secret_provider_status
from xingestion.sessions import SessionHealth, SessionRecord, SessionStore
from xingestion.telemetry import ProtocolTelemetryStore
from xrev.protocol import ProtocolReleaseManifest
from xrev.runtime import WebSessionAuth


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    message: str


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    checks: tuple[PreflightCheck, ...]


class DeploymentPreflight:
    def __init__(
        self,
        *,
        config: AppConfig,
        migration_runner: MigrationRunner,
        manifest: ProtocolReleaseManifest,
        auth: WebSessionAuth,
        base_url: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.config = config
        self.migration_runner = migration_runner
        self.manifest = manifest
        self.auth = auth
        self.base_url = base_url.rstrip("/") if base_url else None
        self.timeout_seconds = timeout_seconds

    def run(self) -> PreflightResult:
        checks = [
            self._check_migrations(),
            self._check_storage(),
            self._check_startup_directories(),
            self._check_secret_backend(),
            self._check_auth(),
            self._check_sessions(),
            self._check_release_risk(),
            self._check_api_shape(),
        ]
        return PreflightResult(
            ok=all(check.status != "FAIL" for check in checks),
            checks=tuple(checks),
        )

    def _check_migrations(self) -> PreflightCheck:
        status = self.migration_runner.status()
        if status.current:
            return PreflightCheck(
                "migrations",
                "PASS",
                f"current versions={','.join(status.applied_versions)}",
            )
        return PreflightCheck(
            "migrations",
            "FAIL",
            f"pending versions={','.join(status.pending_versions)}; run run_migrations.py",
        )

    def _check_storage(self) -> PreflightCheck:
        try:
            self.config.data_dir.mkdir(parents=True, exist_ok=True)
            self.config.raw_evidence_dir.mkdir(parents=True, exist_ok=True)
            probe = self.config.data_dir / ".preflight-write-check"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            return PreflightCheck("storage", "FAIL", f"storage not writable: {exc}")
        return PreflightCheck(
            "storage",
            "PASS",
            f"sqlite={self.config.sqlite_path} raw_evidence={self.config.raw_evidence_dir}",
        )

    def _check_startup_directories(self) -> PreflightCheck:
        directories = {
            "data": self.config.data_dir,
            "raw_evidence": self.config.raw_evidence_dir,
            "reports": self.config.data_dir / "reports",
            "support_exports": self.config.data_dir / "support_exports",
            "protocol_validation": self.config.data_dir / "protocol_validation",
            "logs": load_logging_settings(config=self.config, component="preflight").log_dir,
        }
        failures = []
        for label, path in directories.items():
            try:
                _probe_writable_directory(path)
            except OSError as exc:
                failures.append(f"{label}={path}: {exc}")
        if failures:
            return PreflightCheck(
                "startup_directories",
                "FAIL",
                "; ".join(failures),
            )
        details = " ".join(f"{label}={path}" for label, path in directories.items())
        return PreflightCheck("startup_directories", "PASS", details)

    def _check_secret_backend(self) -> PreflightCheck:
        try:
            status = secret_provider_status(self.config)
        except ValueError as exc:
            return PreflightCheck("secret_backend", "FAIL", str(exc))
        if not status.configured:
            return PreflightCheck(
                "secret_backend",
                "WARN",
                f"provider={status.provider} reference_scheme={status.reference_scheme} {status.message}",
            )
        return PreflightCheck(
            "secret_backend",
            "PASS",
            f"provider={status.provider} reference_scheme={status.reference_scheme}",
        )

    def _check_auth(self) -> PreflightCheck:
        missing = self.auth.missing_fields()
        if missing:
            return PreflightCheck(
                "auth",
                "WARN",
                f"missing fields={','.join(missing)}; live acquisition will not run",
            )
        return PreflightCheck("auth", "PASS", "X web-session auth fields are present")

    def _check_sessions(self) -> PreflightCheck:
        sessions = SessionStore(self.config.sqlite_path).list_sessions()
        available = [session for session in sessions if _session_available(session)]
        if not sessions:
            return PreflightCheck("sessions", "FAIL", "no session metadata rows found")
        if not available:
            return PreflightCheck(
                "sessions",
                "FAIL",
                f"sessions={len(sessions)} available=0; restore or add a healthy session",
            )
        return PreflightCheck(
            "sessions",
            "PASS",
            f"sessions={len(sessions)} available={len(available)}",
        )

    def _check_release_risk(self) -> PreflightCheck:
        release_store = ReleaseStore(self.config.sqlite_path)
        telemetry_store = ProtocolTelemetryStore(self.config.sqlite_path)
        risk = build_release_risk_recommendation(
            manifest=self.manifest,
            release_store=release_store,
            telemetry_store=telemetry_store,
        )
        release = release_store.ensure_release(self.manifest.release_id)
        if release.health in {ReleaseHealth.QUARANTINED, ReleaseHealth.RETIRED}:
            return PreflightCheck(
                "release",
                "FAIL",
                f"release_health={release.health.value} execution blocked",
            )
        status = "FAIL" if risk["action"] == "QUARANTINE_RECOMMENDED" else "PASS"
        return PreflightCheck(
            "release",
            status,
            f"release_health={release.health.value} risk={risk['action']} severity={risk['severity']}",
        )

    def _check_api_shape(self) -> PreflightCheck:
        if not self.base_url:
            return PreflightCheck(
                "api",
                "WARN",
                "skipped; pass --base-url to verify a running deployment",
            )
        required = {
            "/api/health": ("release_id", "auth_ready"),
            "/api/storage": ("sqlite_path", "raw_evidence_dir"),
            "/api/metrics": ("tasks", "release_risk", "sessions"),
            "/api/migrations": ("migrations",),
            "/api/sessions": ("sessions",),
            "/api/releases/current": ("release",),
            "/api/releases/current/risk": ("risk",),
        }
        try:
            for path, keys in required.items():
                payload = self._get(path)
                missing = [key for key in keys if key not in payload]
                if missing:
                    return PreflightCheck(
                        "api",
                        "FAIL",
                        f"{path} missing keys={','.join(missing)}",
                    )
        except RuntimeError as exc:
            return PreflightCheck("api", "FAIL", str(exc))
        return PreflightCheck("api", "PASS", f"shape ok base_url={self.base_url}")

    def _get(self, path: str) -> dict[str, object]:
        url = f"{self.base_url}{path}"
        req = request.Request(url, method="GET")
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get("content-type", "")
                if "application/json" not in content_type:
                    raise RuntimeError(f"{path} returned non-JSON {content_type}")
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"GET {url} failed: {exc}") from exc


def _session_available(session: SessionRecord) -> bool:
    now = datetime.now(UTC).isoformat()
    health_allows = session.health == SessionHealth.HEALTHY or (
        session.health == SessionHealth.DEGRADED
        and session.cooldown_until is not None
        and session.cooldown_until <= now
    )
    cooldown_allows = session.cooldown_until is None or session.cooldown_until <= now
    lease_allows = (
        session.lease_token is None
        or session.lease_expires_at is None
        or session.lease_expires_at <= now
    )
    return health_allows and cooldown_allows and lease_allows


def _probe_writable_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".xingestion-startup-write-check"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
