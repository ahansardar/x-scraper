from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
from typing import Protocol
from urllib import request

from xingestion.sessions.network import network_matches, parse_network_policy


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
        required_process_fragments: tuple[str, ...] = (
            "run_app.py",
            "run_worker.py",
            "run_dispatcher.py",
        ),
        max_unpublished_events: int = 100,
        max_outbox_lag_seconds: int = 300,
        max_redis_pending_entries: int = 100,
        max_redis_pending_idle_seconds: int = 300,
        require_external_data_dir: bool = False,
        required_network_context: str | None = None,
        max_network_failure_rate: float = 0.8,
        min_network_attempts: int = 5,
    ) -> None:
        self.api_client = api_client
        self.root = root.resolve()
        self.process_probe = process_probe
        self.expect_processes = expect_processes
        self.required_process_fragments = required_process_fragments
        self.max_unpublished_events = max_unpublished_events
        self.max_outbox_lag_seconds = max_outbox_lag_seconds
        self.max_redis_pending_entries = max_redis_pending_entries
        self.max_redis_pending_idle_seconds = max_redis_pending_idle_seconds
        self.require_external_data_dir = require_external_data_dir
        self.required_network_context = required_network_context or None
        if self.required_network_context:
            parse_network_policy(self.required_network_context)
        self.max_network_failure_rate = max_network_failure_rate
        self.min_network_attempts = min_network_attempts

    def run(self) -> SupervisionResult:
        checks: list[SupervisionCheck] = []
        try:
            health = self.api_client.get("/api/health")
            storage = self.api_client.get("/api/storage")
            startup = self.api_client.get("/api/startup")
            metrics = self.api_client.get("/api/metrics")
            migrations = self.api_client.get("/api/migrations")
            sessions = self.api_client.get("/api/sessions")
            network_health = self.api_client.get("/api/network-health")
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
                self._check_redis_queue(metrics),
                self._check_recipe_validation_freshness(metrics),
                self._check_protocol_drift(metrics),
                self._check_search_route_monitoring(metrics),
                self._check_sessions(sessions, metrics),
                self._check_network(network_health, sessions),
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

    def _check_redis_queue(self, metrics: dict[str, object]) -> SupervisionCheck:
        redis_queue = _dict(metrics.get("redis_queue"))
        if "error" in redis_queue:
            return SupervisionCheck(
                "redis_queue",
                "FAIL",
                f"redis queue stats unavailable: {redis_queue.get('message', redis_queue.get('error'))}",
            )
        if redis_queue.get("group_exists") is not True:
            return SupervisionCheck(
                "redis_queue",
                "WARN",
                (
                    f"consumer group={redis_queue.get('group_name')} does not exist yet "
                    f"on stream={redis_queue.get('stream_key')}"
                ),
            )
        pending = int(redis_queue.get("pending_count") or 0)
        lag = redis_queue.get("lag")
        idle_ms = redis_queue.get("oldest_pending_idle_ms")
        idle_seconds = int(idle_ms) // 1000 if idle_ms is not None else 0
        if pending > self.max_redis_pending_entries:
            return SupervisionCheck(
                "redis_queue",
                "FAIL",
                f"pending_count={pending} exceeds limit={self.max_redis_pending_entries}",
            )
        if idle_seconds > self.max_redis_pending_idle_seconds:
            return SupervisionCheck(
                "redis_queue",
                "FAIL",
                f"oldest_pending_idle_seconds={idle_seconds} exceeds limit={self.max_redis_pending_idle_seconds}",
            )
        return SupervisionCheck(
            "redis_queue",
            "PASS",
            f"pending_count={pending} lag={lag} oldest_pending_idle_seconds={idle_seconds}",
        )

    def _check_recipe_validation_freshness(self, metrics: dict[str, object]) -> SupervisionCheck:
        entries = [_dict(entry) for entry in _list(metrics.get("recipe_validation_freshness"))]
        if not entries:
            return SupervisionCheck(
                "recipe_validation_freshness",
                "WARN",
                "no recipe validation freshness data available",
            )
        stale = [entry for entry in entries if entry.get("fresh") is not True]
        if stale:
            first = stale[0]
            return SupervisionCheck(
                "recipe_validation_freshness",
                "WARN",
                (
                    f"recipe={first.get('recipe_revision_id')} type={first.get('validation_type')} "
                    f"not fresh: {first.get('reason')} ({len(stale)}/{len(entries)} stale)"
                ),
            )
        return SupervisionCheck(
            "recipe_validation_freshness",
            "PASS",
            f"checked={len(entries)} all fresh",
        )

    def _check_protocol_drift(self, metrics: dict[str, object]) -> SupervisionCheck:
        drift = _dict(metrics.get("protocol_drift"))
        if "error" in drift:
            return SupervisionCheck(
                "protocol_drift",
                "WARN",
                f"protocol drift report unavailable: {drift.get('message', drift.get('error'))}",
            )
        if not drift:
            return SupervisionCheck("protocol_drift", "WARN", "no protocol drift data available")
        if drift.get("drifting") is True:
            return SupervisionCheck(
                "protocol_drift",
                "WARN",
                (
                    f"severity={drift.get('severity')} "
                    f"{drift.get('failures_in_window')}/{drift.get('attempts_in_window')} recent "
                    f"failures: {drift.get('reason')}"
                ),
            )
        return SupervisionCheck(
            "protocol_drift",
            "PASS",
            (
                f"attempts_in_window={drift.get('attempts_in_window')} "
                f"failure_rate={drift.get('failure_rate')}"
            ),
            )

    def _check_search_route_monitoring(self, metrics: dict[str, object]) -> SupervisionCheck:
        route = _dict(metrics.get("search_route_monitoring"))
        if "error" in route:
            return SupervisionCheck(
                "search_route_monitoring",
                "WARN",
                f"search route monitoring unavailable: {route.get('message', route.get('error'))}",
            )
        if not route:
            return SupervisionCheck(
                "search_route_monitoring",
                "WARN",
                "no search route monitoring data available",
            )
        action = str(route.get("action", ""))
        if action in {"RELEASE_BLOCKED", "QUARANTINE_RECOMMENDED"} or str(
            route.get("release_risk_action", "")
        ) == "QUARANTINE_RECOMMENDED":
            return SupervisionCheck(
                "search_route_monitoring",
                "FAIL",
                (
                    f"network_context={route.get('network_context')} action={action} "
                    f"reason={route.get('reason')}"
                ),
            )
        if action in {"NETWORK_REMEDIATION_RECOMMENDED", "ROTATE_OR_PAUSE_ROUTE"}:
            return SupervisionCheck(
                "search_route_monitoring",
                "WARN",
                (
                    f"network_context={route.get('network_context')} action={action} "
                    f"reason={route.get('reason')}"
                ),
            )
        if route.get("has_route_data") is not True:
            return SupervisionCheck(
                "search_route_monitoring",
                "WARN",
                f"no telemetry yet for network_context={route.get('network_context')}",
            )
        return SupervisionCheck(
            "search_route_monitoring",
            "PASS",
            (
                f"network_context={route.get('network_context')} "
                f"route_status={action} release_risk={route.get('release_risk_action')}"
            ),
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

    def _check_network(
        self,
        network_health: dict[str, object],
        sessions_payload: dict[str, object],
    ) -> SupervisionCheck:
        routes = [_dict(route) for route in _list(network_health.get("routes"))]
        sessions = [_dict(session) for session in _list(sessions_payload.get("sessions"))]
        unhealthy_routes = [
            route
            for route in routes
            if int(route.get("total_attempts") or 0) >= self.min_network_attempts
            and float(route.get("failure_rate") or 0.0) > self.max_network_failure_rate
        ]
        if unhealthy_routes:
            route = unhealthy_routes[0]
            return SupervisionCheck(
                "network",
                "FAIL",
                (
                    f"route={route.get('network_context')} failure_rate="
                    f"{float(route.get('failure_rate') or 0.0):.2f} exceeds "
                    f"limit={self.max_network_failure_rate:.2f}"
                ),
            )

        if self.required_network_context:
            matching_sessions = [
                session
                for session in sessions
                if network_matches(
                    str(session.get("network_context") or "direct"),
                    self.required_network_context,
                )
            ]
            healthy_matching = [
                session
                for session in matching_sessions
                if str(session.get("health")) == "HEALTHY"
            ]
            if not healthy_matching:
                return SupervisionCheck(
                    "network",
                    "FAIL",
                    f"no healthy sessions match network_context={self.required_network_context}",
                )
            matching_routes = [
                route
                for route in routes
                if network_matches(
                    str(route.get("network_context") or "direct"),
                    self.required_network_context,
                )
            ]
            if not matching_routes:
                return SupervisionCheck(
                    "network",
                    "WARN",
                    (
                        f"healthy_sessions={len(healthy_matching)} for "
                        f"network_context={self.required_network_context}; no attempts recorded yet"
                    ),
                )
            return SupervisionCheck(
                "network",
                "PASS",
                (
                    f"network_context={self.required_network_context} "
                    f"healthy_sessions={len(healthy_matching)} routes={len(matching_routes)}"
                ),
            )

        return SupervisionCheck(
            "network",
            "PASS",
            f"routes={len(routes)} threshold={self.max_network_failure_rate:.2f}",
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
