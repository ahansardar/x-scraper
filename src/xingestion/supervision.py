from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
from typing import Protocol
from urllib import request


@dataclass(frozen=True)
class SupervisionCheck:
    name: str
    status: str
    message: str


@dataclass(frozen=True)
class SupervisionResult:
    ok: bool
    checks: tuple[SupervisionCheck, ...]


class ApiClient(Protocol):
    def get(self, path: str) -> dict[str, object]:
        """Return decoded JSON from a deployment endpoint."""


class ProcessProbe(Protocol):
    def command_lines(self) -> tuple[str, ...]:
        """Return visible local process command lines."""


class UrlApiClient:
    def __init__(self, *, base_url: str, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get(self, path: str) -> dict[str, object]:
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


class WindowsProcessProbe:
    def command_lines(self) -> tuple[str, ...]:
        script = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine } | "
            "Select-Object -ExpandProperty CommandLine"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "process table probe failed")
        return tuple(
            line.strip()
            for line in completed.stdout.splitlines()
            if line.strip()
        )


class DeploymentSupervisorCheck:
    def __init__(
        self,
        *,
        api_client: ApiClient,
        root: Path,
        process_probe: ProcessProbe | None = None,
        expect_processes: bool = False,
        required_process_fragments: tuple[str, ...] = ("run_app.py", "run_worker.py"),
        max_unpublished_events: int = 100,
        max_outbox_lag_seconds: int = 300,
        require_external_data_dir: bool = False,
    ) -> None:
        self.api_client = api_client
        self.root = root.resolve()
        self.process_probe = process_probe
        self.expect_processes = expect_processes
        self.required_process_fragments = required_process_fragments
        self.max_unpublished_events = max_unpublished_events
        self.max_outbox_lag_seconds = max_outbox_lag_seconds
        self.require_external_data_dir = require_external_data_dir

    def run(self) -> SupervisionResult:
        checks: list[SupervisionCheck] = []
        try:
            health = self.api_client.get("/api/health")
            storage = self.api_client.get("/api/storage")
            startup = self.api_client.get("/api/startup")
            metrics = self.api_client.get("/api/metrics")
            migrations = self.api_client.get("/api/migrations")
            sessions = self.api_client.get("/api/sessions")
            release = self.api_client.get("/api/releases/current")
        except RuntimeError as exc:
            return SupervisionResult(
                ok=False,
                checks=(
                    SupervisionCheck(
                        "api",
                        "FAIL",
                        str(exc),
                    ),
                ),
            )

        checks.extend(
            (
                self._check_health(health),
                self._check_migrations(migrations),
                self._check_storage(storage),
                self._check_startup(startup),
                self._check_queue(metrics),
                self._check_sessions(sessions, metrics),
                self._check_release(release),
            )
        )
        checks.append(self._check_processes())
        return SupervisionResult(
            ok=all(check.status != "FAIL" for check in checks),
            checks=tuple(checks),
        )

    def _check_health(self, health: dict[str, object]) -> SupervisionCheck:
        if health.get("ok") is not True:
            return SupervisionCheck("web", "FAIL", "health endpoint did not report ok=true")
        release_id = str(health.get("release_id", ""))
        dispatch = str(health.get("dispatch", ""))
        if not release_id:
            return SupervisionCheck("web", "FAIL", "health endpoint is missing release_id")
        return SupervisionCheck(
            "web",
            "PASS",
            f"release={release_id} dispatch={dispatch}",
        )

    def _check_migrations(self, payload: dict[str, object]) -> SupervisionCheck:
        migrations = _dict(payload.get("migrations"))
        pending = _list(migrations.get("pending_versions"))
        if migrations.get("current") is not True:
            return SupervisionCheck(
                "migrations",
                "FAIL",
                f"pending versions={','.join(str(item) for item in pending)}",
            )
        applied = _list(migrations.get("applied_versions"))
        return SupervisionCheck(
            "migrations",
            "PASS",
            f"current versions={','.join(str(item) for item in applied)}",
        )

    def _check_storage(self, storage: dict[str, object]) -> SupervisionCheck:
        data_dir = Path(str(storage.get("data_dir", ""))).resolve()
        sqlite_path = str(storage.get("sqlite_path", ""))
        raw_evidence_dir = str(storage.get("raw_evidence_dir", ""))
        if not sqlite_path or not raw_evidence_dir:
            return SupervisionCheck("storage", "FAIL", "storage paths are incomplete")
        if self.require_external_data_dir and _is_relative_to(data_dir, self.root):
            return SupervisionCheck(
                "storage",
                "FAIL",
                f"data_dir is inside checkout; move XINGESTION_DATA_DIR to persistent storage: {data_dir}",
            )
        return SupervisionCheck(
            "storage",
            "PASS",
            f"data_dir={data_dir} sqlite={sqlite_path} raw_evidence={raw_evidence_dir}",
        )

    def _check_startup(self, startup: dict[str, object]) -> SupervisionCheck:
        checks = _list(startup.get("checks"))
        failures = [
            _dict(check)
            for check in checks
            if _dict(check).get("status") == "FAIL"
        ]
        if startup.get("ok") is not True:
            detail = "; ".join(
                f"{check.get('name')}: {check.get('message')}"
                for check in failures
            )
            return SupervisionCheck(
                "startup",
                "FAIL",
                detail or "startup readiness failed",
            )
        return SupervisionCheck(
            "startup",
            "PASS",
            f"checks={len(checks)}",
        )

    def _check_queue(self, metrics: dict[str, object]) -> SupervisionCheck:
        outbox = _dict(metrics.get("outbox"))
        unpublished = int(outbox.get("unpublished_events") or 0)
        lag = outbox.get("oldest_unpublished_lag_seconds")
        lag_seconds = int(lag) if lag is not None else 0
        if unpublished > self.max_unpublished_events:
            return SupervisionCheck(
                "queue",
                "FAIL",
                f"unpublished_events={unpublished} exceeds limit={self.max_unpublished_events}",
            )
        if lag_seconds > self.max_outbox_lag_seconds:
            return SupervisionCheck(
                "queue",
                "FAIL",
                f"oldest_unpublished_lag_seconds={lag_seconds} exceeds limit={self.max_outbox_lag_seconds}",
            )
        return SupervisionCheck(
            "queue",
            "PASS",
            f"unpublished_events={unpublished} oldest_lag_seconds={lag_seconds}",
        )

    def _check_sessions(
        self,
        sessions_payload: dict[str, object],
        metrics: dict[str, object],
    ) -> SupervisionCheck:
        sessions = _list(sessions_payload.get("sessions"))
        session_metrics = _dict(metrics.get("sessions"))
        healthy = int(session_metrics.get("healthy") or 0)
        if not sessions:
            return SupervisionCheck("sessions", "FAIL", "no session metadata rows found")
        if healthy < 1:
            return SupervisionCheck("sessions", "FAIL", "no healthy sessions are available")
        return SupervisionCheck(
            "sessions",
            "PASS",
            f"sessions={len(sessions)} healthy={healthy}",
        )

    def _check_release(self, payload: dict[str, object]) -> SupervisionCheck:
        release = _dict(payload.get("release"))
        health = str(release.get("health", ""))
        release_id = str(release.get("release_id", ""))
        if health in {"QUARANTINED", "RETIRED"}:
            return SupervisionCheck(
                "release",
                "FAIL",
                f"release={release_id} health={health} execution blocked",
            )
        if not release_id:
            return SupervisionCheck("release", "FAIL", "release payload is missing release_id")
        return SupervisionCheck(
            "release",
            "PASS",
            f"release={release_id} health={health}",
        )

    def _check_processes(self) -> SupervisionCheck:
        if not self.expect_processes:
            return SupervisionCheck(
                "processes",
                "WARN",
                "process table check skipped; pass --expect-processes in supervised deployments",
            )
        if self.process_probe is None:
            return SupervisionCheck("processes", "FAIL", "no process probe is configured")
        try:
            commands = self.process_probe.command_lines()
        except RuntimeError as exc:
            return SupervisionCheck("processes", "FAIL", str(exc))
        missing = [
            fragment
            for fragment in self.required_process_fragments
            if not _contains_fragment(commands, fragment)
        ]
        if missing:
            return SupervisionCheck(
                "processes",
                "FAIL",
                f"missing process command fragments={','.join(missing)}",
            )
        return SupervisionCheck(
            "processes",
            "PASS",
            f"found command fragments={','.join(self.required_process_fragments)}",
        )


def _contains_fragment(commands: tuple[str, ...], fragment: str) -> bool:
    fragment_lower = fragment.lower()
    return any(fragment_lower in command.lower() for command in commands)


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
