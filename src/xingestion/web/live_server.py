from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xingestion.capabilities import (
    CapabilityPlanner,
    CapabilityRequest,
    SearchTweetsInput,
)
from xingestion.canonical import CanonicalStore
from xingestion.config import AppConfig, load_app_config
from xingestion.investigation import (
    build_network_route_recommendations,
    build_protocol_drift_package,
    build_release_risk_recommendation,
)
from xingestion.logging_config import configure_logging
from xingestion.migrations import MigrationRunner
from xingestion.operator_tasks import list_operator_task_actions
from xingestion.outbox_operations import list_outbox_queue, process_outbox
from xingestion.preflight import DeploymentPreflight
from xingestion.protocol_validation import (
    build_capture_replay_comparison_report,
    build_protocol_validation_report,
    list_protocol_validation_reports,
    run_direct_replays_for_browser_captures,
    write_protocol_validation_report,
)
from xingestion.sessions import SessionHealth, SessionStore, import_session_registry
from xingestion.releases import ReleaseHealth, ReleaseStore, resolve_approved_manifest
from xingestion.reprocessing import ReprocessJobStore, reprocess_task_evidence
from xingestion.secrets import (
    build_secret_provider,
    resolve_web_session_auth,
    secret_provider_status,
)
from xingestion.support_export import (
    apply_support_export_retention,
    list_support_exports,
    read_support_export,
    support_export_file,
    write_failed_task_export,
)
from xingestion.telemetry import ProtocolTelemetryStore
from xingestion.tasks import SQLiteTaskLedger, TaskState
from xingestion.workers import LocalWorker
from xingestion.xprotocol.evidence import FileRawEvidenceSink
from xingestion.xprotocol.protocol import CapabilityId
from xingestion.xprotocol.runtime import (
    UrllibJsonTransport,
    load_env_file,
)


STATIC_ROOT = ROOT / "src" / "xingestion" / "web" / "static"
MANIFEST_DIR = ROOT / "protocol_releases"
LOGGER = logging.getLogger("xingestion.web")


class LiveAppState:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.raw_evidence_dir.mkdir(parents=True, exist_ok=True)
        self.migration_runner = MigrationRunner(
            self.config.sqlite_path,
            ROOT / "src" / "xingestion" / "migrations" / "sql",
        )
        self.migration_status = (
            self.migration_runner.require_current()
            if self.config.require_migrations
            else self.migration_runner.status()
        )
        self.ledger = SQLiteTaskLedger(self.config.sqlite_path)
        self.canonical_store = CanonicalStore(self.config.sqlite_path)
        self.release_store = ReleaseStore(self.config.sqlite_path)
        self.resolved_release = resolve_approved_manifest(
            release_store=self.release_store,
            manifest_dir=MANIFEST_DIR,
        )
        self.manifest = self.resolved_release.manifest
        self.manifest_path = self.resolved_release.manifest_path
        self.planner = CapabilityPlanner(self.manifest)
        self.evidence_sink = FileRawEvidenceSink(self.config.raw_evidence_dir)
        self.transport = UrllibJsonTransport()
        self.auth = resolve_web_session_auth(self.config)
        self.secret_provider = build_secret_provider(self.config)
        self.session_store = SessionStore(self.config.sqlite_path)
        self.telemetry_store = ProtocolTelemetryStore(self.config.sqlite_path)
        self.reprocess_jobs = ReprocessJobStore(self.config.sqlite_path)
        self.session_store.upsert_session(
            session_id=self.config.default_session_id,
            account_label=self.config.default_account_label,
            credential_ref=self.config.default_credential_ref,
            network_context=self.config.default_network_context,
            health=(
                SessionHealth.HEALTHY
                if not self.auth.missing_fields()
                else SessionHealth.AUTH_EXPIRED
            ),
        )
        if self.config.session_registry_path is not None:
            import_session_registry(
                store=self.session_store,
                path=self.config.session_registry_path,
            )
        self.worker = LocalWorker(
            ledger=self.ledger,
            manifest=self.manifest,
            auth=self.auth,
            transport=self.transport,
            raw_evidence_sink=self.evidence_sink,
            canonical_store=self.canonical_store,
            release_store=self.release_store,
            session_store=self.session_store,
            telemetry_store=self.telemetry_store,
            secret_provider=self.secret_provider,
            required_network_context=self.config.worker_network_context or None,
        )


STATE: LiveAppState | None = None


class LiveAppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            return self._json(
                {
                    "ok": True,
                    "release_id": STATE.manifest.release_id,
                    "mode": "live",
                    "auth_ready": not STATE.auth.missing_fields(),
                    "dispatch": "outbox-local-worker",
                    "storage": _storage_dict(),
                }
            )
        if parsed.path == "/api/metrics":
            return self._json(_metrics_dict())
        if parsed.path == "/api/migrations":
            return self._json({"migrations": _migration_status_dict(STATE.migration_runner.status())})
        if parsed.path == "/api/telemetry":
            return self._json({"telemetry": _telemetry_summary_dict(STATE.telemetry_store.summary())})
        if parsed.path == "/api/network-health":
            return self._json(_network_health_dict())
        if parsed.path == "/api/releases/current":
            return self._json({"release": _release_dict(STATE.release_store.ensure_release(STATE.manifest.release_id))})
        if parsed.path == "/api/releases/current/risk":
            return self._json({"risk": _release_risk_dict()})
        if parsed.path == "/api/storage":
            return self._json(_storage_dict())
        if parsed.path == "/api/startup":
            return self._json(_startup_dict())
        if parsed.path == "/api/protocol-validation":
            return self._json({"validation": _protocol_validation_dict()})
        if parsed.path == "/api/protocol-validation/reports":
            reports = list_protocol_validation_reports(
                STATE.config.data_dir / "protocol_validation",
                limit=25,
            )
            return self._json(
                {
                    "report_dir": str(STATE.config.data_dir / "protocol_validation"),
                    "reports": [report.public_dict() for report in reports],
                }
            )
        if parsed.path == "/api/sessions":
            return self._json({"sessions": [_session_dict(s) for s in STATE.session_store.list_sessions()]})
        if parsed.path == "/api/retention":
            return self._json(
                {
                    "retention_days": STATE.config.retention_days,
                    "dry_run": _retention_dict(
                        STATE.ledger.apply_retention(
                            days=STATE.config.retention_days,
                            dry_run=True,
                        )
                    ),
                }
            )
        if parsed.path == "/api/canonical/tweets":
            return self._json(
                {
                    "counts": STATE.canonical_store.counts(),
                    "latest_engagements": [
                        _engagement_dict(item)
                        for item in STATE.canonical_store.latest_engagements()
                    ],
                }
            )
        if parsed.path == "/api/tasks":
            return self._json({"tasks": self._list_tasks()})
        if parsed.path == "/api/task-actions":
            actions = list_operator_task_actions(STATE.config.sqlite_path, limit=25)
            return self._json({"actions": [_task_action_dict(action) for action in actions]})
        if parsed.path == "/api/outbox":
            try:
                return self._json(list_outbox_queue(STATE.ledger, limit=25))
            except ValueError as exc:
                return self._json({"message": str(exc)}, status=400)
        if parsed.path == "/api/support-exports":
            exports = list_support_exports(STATE.config, limit=25)
            retention = apply_support_export_retention(
                STATE.config,
                days=STATE.config.retention_days,
                dry_run=True,
            )
            return self._json(
                {
                    "export_dir": str(STATE.config.data_dir / "support_exports"),
                    "retention_days": STATE.config.retention_days,
                    "exports": [item.public_dict() for item in exports],
                    "dry_run": retention.public_dict(),
                }
            )
        if parsed.path.startswith("/api/support-exports/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "download":
                if not self._require_admin():
                    return
                return self._download_support_export(unquote(parts[2]))
            if len(parts) == 3:
                return self._support_export_detail(unquote(parts[2]))
        if parsed.path.startswith("/api/tasks/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 3:
                return self._task_detail(parts[2])
            if len(parts) == 4 and parts[3] == "result":
                return self._task_result(parts[2])
        if parsed.path.startswith("/api/"):
            return self._api_not_found(parsed.path)
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/sessions/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "restore":
                if not self._require_admin():
                    return
                return self._restore_session(parts[2])
            if len(parts) == 4 and parts[3] == "disable":
                if not self._require_admin():
                    return
                return self._disable_session(parts[2])

        if parsed.path.startswith("/api/tasks/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "replay":
                if not self._require_admin():
                    return
                return self._replay_task(parts[2])
            if len(parts) == 4 and parts[3] == "cancel":
                if not self._require_admin():
                    return
                return self._cancel_task(parts[2])
            if len(parts) == 4 and parts[3] == "reprocess":
                if not self._require_admin():
                    return
                return self._reprocess_task(parts[2])
            if len(parts) == 4 and parts[3] == "investigate":
                if not self._require_admin():
                    return
                return self._investigate_task(parts[2])
            if len(parts) == 4 and parts[3] == "export":
                if not self._require_admin():
                    return
                return self._export_failed_task(parts[2])

        if parsed.path == "/api/retention/run":
            if not self._require_admin():
                return
            return self._run_retention()
        if parsed.path == "/api/support-exports/retention":
            if not self._require_admin():
                return
            return self._run_support_export_retention()
        if parsed.path == "/api/sessions/import":
            if not self._require_admin():
                return
            return self._import_sessions()
        if parsed.path == "/api/outbox/process":
            if not self._require_admin():
                return
            return self._process_outbox(self._read_json())
        if parsed.path == "/api/protocol-validation/run":
            if not self._require_admin():
                return
            return self._run_protocol_validation()
        if parsed.path == "/api/releases/current/quarantine":
            if not self._require_admin():
                return
            return self._set_release_health(ReleaseHealth.QUARANTINED, "operator_quarantine")
        if parsed.path == "/api/releases/current/activate":
            if not self._require_admin():
                return
            return self._set_release_health(ReleaseHealth.ACTIVE, "operator_activate")
        if parsed.path == "/api/reprocess/jobs":
            if not self._require_admin():
                return
            return self._run_reprocess_job(self._read_json())

        if parsed.path == "/api/capability-tasks":
            return self._create_capability_task(self._read_json())

        if parsed.path != "/api/search-tweets":
            return self._api_not_found(parsed.path)

        return self._create_search_tweets_task(self._read_json())

    def _create_search_tweets_task(self, body):
        query = str(body.get("query", "")).strip()
        product = str(body.get("product", "Top"))
        page_size = int(body.get("page_size", 20))
        max_pages = int(body.get("max_pages", 1))
        idempotency_key = str(
            body.get("idempotency_key")
            or f"live:{query}:{product}:{page_size}:{max_pages}"
        )
        capability_request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(
                query=query,
                product=product,
                page_size=page_size,
                max_pages=max_pages,
            ),
        )
        return self._queue_capability_request(capability_request, idempotency_key)

    def _create_capability_task(self, body):
        capability_id = str(body.get("capability_id", "")).strip()
        contract_version = int(body.get("contract_version", 1))
        payload = body.get("payload", {})
        if capability_id != CapabilityId.SEARCH_TWEETS.value:
            return self._json({"message": f"Unsupported capability {capability_id}"}, status=400)
        if not isinstance(payload, dict):
            return self._json({"message": "payload must be an object"}, status=400)

        try:
            capability_request = CapabilityRequest(
                capability_id=CapabilityId.SEARCH_TWEETS,
                contract_version=contract_version,
                payload=SearchTweetsInput(
                    query=str(payload.get("query", "")),
                    product=str(payload.get("product", "Top")),
                    cursor=payload.get("cursor"),
                    page_size=int(payload.get("page_size", 20)),
                    max_pages=int(payload.get("max_pages", 1)),
                    page_number=int(payload.get("page_number", 1)),
                    pagination_root_task_id=payload.get("pagination_root_task_id"),
                    pagination_parent_task_id=payload.get("pagination_parent_task_id"),
                ),
            )
            idempotency_key = str(
                body.get("idempotency_key")
                or f"capability:{capability_id}:{json.dumps(payload, sort_keys=True)}"
            )
        except (TypeError, ValueError) as exc:
            return self._json({"message": str(exc)}, status=400)

        return self._queue_capability_request(capability_request, idempotency_key)

    def _queue_capability_request(self, capability_request, idempotency_key):
        active = STATE.ledger.active_task_count(
            capability_id=capability_request.capability_id
        )
        limit = STATE.config.max_active_tasks_per_capability
        if active >= limit:
            return self._json(
                {
                    "message": "Backpressure limit reached",
                    "capability_id": capability_request.capability_id.value,
                    "active_tasks": active,
                    "limit": limit,
                },
                status=429,
            )
        plan = STATE.planner.plan(capability_request)
        task = STATE.ledger.create_task(
            idempotency_key=idempotency_key,
            capability_id=capability_request.capability_id,
            contract_version=capability_request.contract_version,
            request_json=capability_request.public_dict(),
            plan_json=plan.public_dict(),
        )
        outbox_process = self._process_ready_outbox(limit=5)

        return self._json(
            {
                "task": _task_dict(task),
                "message": "Task queued",
                "status_url": f"/api/tasks/{task.task_id}",
                "result_url": f"/api/tasks/{task.task_id}/result",
                "outbox_process": (
                    outbox_process.public_dict() if outbox_process is not None else None
                ),
            },
            status=202,
        )

    def _replay_task(self, task_id):
        try:
            task = STATE.ledger.replay_task(task_id)
        except ValueError as exc:
            status = 404 if "not found" in str(exc).lower() else 409
            return self._json({"message": str(exc)}, status=status)
        outbox_process = self._process_ready_outbox(limit=5)

        return self._json(
            {
                "task": _task_dict(task),
                "message": "Replay task queued",
                "status_url": f"/api/tasks/{task.task_id}",
                "result_url": f"/api/tasks/{task.task_id}/result",
                "outbox_process": (
                    outbox_process.public_dict() if outbox_process is not None else None
                ),
            },
            status=201,
        )

    def _cancel_task(self, task_id):
        try:
            task = STATE.ledger.cancel_task(task_id)
        except ValueError as exc:
            status = 404 if "not found" in str(exc).lower() else 409
            return self._json({"message": str(exc)}, status=status)

        return self._json(
            {
                "task": _task_dict(task),
                "message": "Task cancelled",
                "status_url": f"/api/tasks/{task.task_id}",
            },
            status=200,
        )

    def _run_retention(self):
        result = STATE.ledger.apply_retention(
            days=STATE.config.retention_days,
            dry_run=False,
        )
        return self._json({"retention": _retention_dict(result)}, status=200)

    def _run_support_export_retention(self):
        result = apply_support_export_retention(
            STATE.config,
            days=STATE.config.retention_days,
            dry_run=False,
        )
        return self._json({"retention": result.public_dict()}, status=200)

    def _process_outbox(self, body):
        limit = int(body.get("limit", 5))
        try:
            result = self._process_ready_outbox(limit=limit)
        except ValueError as exc:
            return self._json({"message": str(exc)}, status=400)
        if result is None:
            return self._json({"message": "Worker is not configured"}, status=503)
        return self._json({"outbox_process": result.public_dict()}, status=200)

    def _process_ready_outbox(self, *, limit):
        worker = getattr(STATE, "worker", None)
        if worker is None:
            return None
        return process_outbox(
            ledger=STATE.ledger,
            worker=worker,
            limit=limit,
        )

    def _run_protocol_validation(self):
        report = build_protocol_validation_report(
            raw_evidence_dir=STATE.config.raw_evidence_dir,
            parser_revision_id=STATE.manifest.bindings[0].recipe.parser.revision_id,
            limit=10,
            include_fixtures=True,
        )
        direct_replay = run_direct_replays_for_browser_captures(
            raw_evidence_dir=STATE.config.raw_evidence_dir,
            manifest=STATE.manifest,
            auth=STATE.auth,
            transport=STATE.transport,
            raw_evidence_sink=STATE.evidence_sink,
            limit=3,
        )
        comparison = build_capture_replay_comparison_report(
            raw_evidence_dir=STATE.config.raw_evidence_dir,
            limit=10,
        )
        path = write_protocol_validation_report(
            report,
            report_dir=STATE.config.data_dir / "protocol_validation",
        )
        return self._json(
            {
                "validation": report.public_dict(),
                "direct_replay": direct_replay.public_dict(),
                "capture_replay_comparison": comparison.public_dict(),
                "saved_path": str(path),
            },
            status=201,
        )

    def _support_export_detail(self, name):
        try:
            export = read_support_export(STATE.config, name)
        except ValueError as exc:
            status = 404 if "not found" in str(exc).lower() else 400
            return self._json({"message": str(exc)}, status=status)
        return self._json({"export": export}, status=200)

    def _download_support_export(self, name):
        try:
            path = support_export_file(STATE.config, name)
        except ValueError as exc:
            status = 404 if "not found" in str(exc).lower() else 400
            return self._json({"message": str(exc)}, status=status)

        content = path.read_bytes()
        self.send_response(200)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(content)))
        self.send_header("content-disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(content)

    def _set_release_health(self, health, reason):
        release = STATE.release_store.set_health(
            STATE.manifest.release_id,
            health=health,
            reason=reason,
        )
        return self._json({"release": _release_dict(release)}, status=200)

    def _restore_session(self, session_id):
        try:
            session = STATE.session_store.update_health(
                session_id,
                health=SessionHealth.HEALTHY,
                reason="operator_restore",
            )
        except ValueError as exc:
            return self._json({"message": str(exc)}, status=404)
        return self._json(
            {
                "session": _session_dict(session),
                "message": "Session restored",
            },
            status=200,
        )

    def _disable_session(self, session_id):
        try:
            session = STATE.session_store.update_health(
                session_id,
                health=SessionHealth.DISABLED,
                reason="operator_disable",
            )
        except ValueError as exc:
            return self._json({"message": str(exc)}, status=404)
        return self._json(
            {
                "session": _session_dict(session),
                "message": "Session disabled",
            },
            status=200,
        )

    def _import_sessions(self):
        if STATE.config.session_registry_path is None:
            return self._json(
                {"message": "XINGESTION_SESSION_REGISTRY is not configured"},
                status=400,
            )
        try:
            result = import_session_registry(
                store=STATE.session_store,
                path=STATE.config.session_registry_path,
            )
        except (OSError, ValueError) as exc:
            return self._json({"message": str(exc)}, status=400)
        return self._json({"session_import": result.public_dict()}, status=201)

    def _reprocess_task(self, task_id):
        try:
            result = reprocess_task_evidence(
                task_id=task_id,
                ledger=STATE.ledger,
                canonical_store=STATE.canonical_store,
            )
        except ValueError as exc:
            status = 404 if "not found" in str(exc).lower() else 409
            return self._json({"message": str(exc)}, status=status)
        return self._json({"reprocess": _reprocess_result_dict(result)}, status=200)

    def _investigate_task(self, task_id):
        try:
            package = build_protocol_drift_package(
                task_id=task_id,
                ledger=STATE.ledger,
                manifest=STATE.manifest,
                release_store=STATE.release_store,
                session_store=STATE.session_store,
                telemetry_store=STATE.telemetry_store,
            )
        except ValueError as exc:
            return self._json({"message": str(exc)}, status=404)
        return self._json({"investigation": package}, status=200)

    def _export_failed_task(self, task_id):
        try:
            result = write_failed_task_export(
                task_id=task_id,
                config=STATE.config,
                manifest=STATE.manifest,
            )
        except ValueError as exc:
            return self._json({"message": str(exc)}, status=400)
        return self._json(
            {
                "export": {
                    "path": str(result.path),
                    "package_type": result.package["package_type"],
                    "task_id": result.package["task_id"],
                    "state": result.package["state"],
                    "support_summary": result.package["support_summary"],
                    "redaction": result.package["redaction"],
                }
            },
            status=201,
        )

    def _run_reprocess_job(self, body):
        release_id = str(body.get("release_id") or STATE.manifest.release_id)
        limit = int(body.get("limit", 100))
        try:
            job = STATE.reprocess_jobs.run_for_release(
                release_id=release_id,
                ledger=STATE.ledger,
                canonical_store=STATE.canonical_store,
                limit=limit,
            )
        except ValueError as exc:
            return self._json({"message": str(exc)}, status=400)
        return self._json({"job": _reprocess_job_dict(job)}, status=201)

    def _api_not_found(self, path):
        return self._json({"message": f"API route not found: {path}"}, status=404)

    def _read_json(self):
        length = int(self.headers.get("content-length", "0"))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON body: {exc.msg}") from exc

    def _require_admin(self):
        return True

    def _json(self, payload, *, status=200):
        encoded = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _list_tasks(self):
        import sqlite3

        path = STATE.config.sqlite_path
        if not path.exists():
            return []
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM capability_tasks ORDER BY created_at DESC LIMIT 25"
            ).fetchall()
        return [
            {
                "task_id": row["task_id"],
                "idempotency_key": row["idempotency_key"],
                "capability_id": row["capability_id"],
                "state": row["state"],
                "replay_origin_task_id": row["replay_origin_task_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def _task_detail(self, task_id):
        task = STATE.ledger.get_task(task_id)
        if task is None:
            return self._json({"message": "Task not found"}, status=404)
        return self._json({"task": _task_dict(task)})

    def _task_result(self, task_id):
        task = STATE.ledger.get_task(task_id)
        if task is None:
            return self._json({"message": "Task not found"}, status=404)
        if task.state == TaskState.DEAD_LETTER:
            return self._json(
                {"task": _task_dict(task), "error": task.error_json},
                status=502,
            )
        if task.state != TaskState.DONE or not task.result_json:
            return self._json(
                {"task": _task_dict(task), "message": "Result not ready"},
                status=202,
            )

        raw_evidence = task.result_json["raw_evidence"]
        page = _load_page_from_evidence(
            raw_evidence["storage_uri"],
            _raw_evidence_ref_from_json(raw_evidence),
        )
        return self._json(
            {
                "task": _task_dict(task),
                "plan": task.plan_json,
                "raw_evidence": raw_evidence,
                "page": {
                    "next_cursor": page.next_cursor,
                    "tweets": [_tweet_dict(tweet) for tweet in page.tweets],
                },
            }
        )


def _task_dict(task):
    return {
        "task_id": task.task_id,
        "idempotency_key": task.idempotency_key,
        "capability_id": task.capability_id.value,
        "contract_version": task.contract_version,
        "state": task.state.value,
        "has_result": task.result_json is not None,
        "has_error": task.error_json is not None,
        "attempt_count": task.attempt_count,
        "max_attempts": task.max_attempts,
        "next_attempt_at": task.next_attempt_at,
        "lease_owner": task.lease_owner,
        "lease_expires_at": task.lease_expires_at,
        "delivery_generation": task.delivery_generation,
        "replay_origin_task_id": task.replay_origin_task_id,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _task_action_dict(action):
    return action.public_dict()


def _tweet_dict(tweet):
    return {
        "tweet_id": tweet.tweet_id,
        "username": tweet.username,
        "name": tweet.name,
        "text": tweet.text,
        "source_created_at": tweet.source_created_at,
        "reply_count": tweet.reply_count,
        "repost_count": tweet.repost_count,
        "like_count": tweet.like_count,
        "quote_count": tweet.quote_count,
        "bookmark_count": tweet.bookmark_count,
        "view_count": tweet.view_count,
        "canonical_url": tweet.canonical_url,
    }


def _load_page_from_evidence(storage_uri, raw_evidence_ref):
    from xingestion.xprotocol.runtime import parse_search_tweets_page

    payload = json.loads(Path(storage_uri).read_text(encoding="utf-8"))
    return parse_search_tweets_page(payload, raw_evidence_ref=raw_evidence_ref)


def _raw_evidence_ref_from_json(raw_evidence):
    from xingestion.xprotocol.evidence import RawEvidenceRef

    return RawEvidenceRef(
        evidence_id=raw_evidence["evidence_id"],
        content_sha256=raw_evidence["content_sha256"],
        media_type="application/json",
        storage_uri=raw_evidence["storage_uri"],
        captured_at="",
        metadata={},
    )


def _storage_dict():
    return {
        "data_dir": str(STATE.config.data_dir),
        "sqlite_path": str(STATE.config.sqlite_path),
        "raw_evidence_dir": str(STATE.config.raw_evidence_dir),
        "approved_release_id": STATE.release_store.approved_release_id(),
        "manifest_path": str(STATE.manifest_path),
        "retention_days": STATE.config.retention_days,
        "operator_auth_required": False,
        "secret_provider": STATE.config.secret_provider,
        "secret_backend": secret_provider_status(STATE.config).public_dict(),
        "session_registry_configured": STATE.config.session_registry_path is not None,
        "session_registry_path": (
            str(STATE.config.session_registry_path)
            if STATE.config.session_registry_path is not None
            else None
        ),
        "require_migrations": STATE.config.require_migrations,
        "max_active_tasks_per_capability": STATE.config.max_active_tasks_per_capability,
    }


def _startup_dict():
    result = DeploymentPreflight(
        config=STATE.config,
        migration_runner=STATE.migration_runner,
        manifest=STATE.manifest,
        auth=STATE.auth,
    ).run()
    return {
        "ok": result.ok,
        "checks": [
            {
                "name": check.name,
                "status": check.status,
                "message": check.message,
            }
            for check in result.checks
        ],
    }


def _protocol_validation_dict():
    report = build_protocol_validation_report(
        raw_evidence_dir=STATE.config.raw_evidence_dir,
        parser_revision_id=STATE.manifest.bindings[0].recipe.parser.revision_id,
        limit=10,
        include_fixtures=True,
    )
    payload = report.public_dict()
    payload["capture_replay_comparison"] = build_capture_replay_comparison_report(
        raw_evidence_dir=STATE.config.raw_evidence_dir,
        limit=10,
    ).public_dict()
    return payload


def _metrics_dict():
    task_counts = STATE.ledger.task_state_counts()
    canonical_counts = STATE.canonical_store.counts()
    sessions = STATE.session_store.list_sessions()
    return {
        "release_id": STATE.manifest.release_id,
        "release": _release_dict(STATE.release_store.ensure_release(STATE.manifest.release_id)),
        "auth_ready": not STATE.auth.missing_fields(),
        "tasks": {
            "state_counts": task_counts,
            "active": (
                task_counts["CREATED"]
                + task_counts["ENQUEUED"]
                + task_counts["RUNNING"]
                + task_counts["RETRY_SCHEDULED"]
            ),
            "terminal": (
                task_counts["DONE"]
                + task_counts["DEAD_LETTER"]
                + task_counts["CANCELLED"]
            ),
            "max_active_tasks_per_capability": STATE.config.max_active_tasks_per_capability,
        },
        "outbox": STATE.ledger.outbox_stats(),
        "canonical": canonical_counts,
        "storage": _storage_dict(),
        "migrations": _migration_status_dict(STATE.migration_runner.status()),
        "telemetry": _telemetry_summary_dict(STATE.telemetry_store.summary()),
        "release_risk": _release_risk_dict(),
        "sessions": {
            "total": len(sessions),
            "healthy": sum(
                1
                for session in sessions
                if session.health == SessionHealth.HEALTHY
            ),
            "cooling_down": sum(
                1
                for session in sessions
                if session.cooldown_until is not None
            ),
        },
    }


def _migration_status_dict(status):
    return {
        "current": status.current,
        "available_versions": list(status.available_versions),
        "applied_versions": list(status.applied_versions),
        "pending_versions": list(status.pending_versions),
    }


def _telemetry_summary_dict(summary):
    return {
        "total_attempts": summary.total_attempts,
        "successes": summary.successes,
        "failures": summary.failures,
        "errors_by_class": summary.errors_by_class,
    }


def _network_health_dict():
    route_recommendations = {
        item["network_context"]: item
        for item in build_network_route_recommendations(
            telemetry_store=STATE.telemetry_store,
            release_id=STATE.manifest.release_id,
        )
    }
    routes = [
        _network_route_dict(route, route_recommendations.get(route.network_context))
        for route in STATE.telemetry_store.network_summary(release_id=STATE.manifest.release_id)
    ]
    return {
        "release_id": STATE.manifest.release_id,
        "worker_network_context": STATE.config.worker_network_context or None,
        "routes": routes,
        "recommendations": list(route_recommendations.values()),
    }


def _network_route_dict(route, recommendation=None):
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


def _release_risk_dict():
    return build_release_risk_recommendation(
        manifest=STATE.manifest,
        release_store=STATE.release_store,
        telemetry_store=STATE.telemetry_store,
    )


def _reprocess_result_dict(result):
    return {
        "task_id": result.task_id,
        "raw_evidence_id": result.raw_evidence_id,
        "parsed_tweets": result.parsed_tweets,
        "canonical_counts": result.canonical_counts,
    }


def _reprocess_job_dict(job):
    return {
        "job_id": job.job_id,
        "release_id": job.release_id,
        "state": job.state,
        "matched_tasks": job.matched_tasks,
        "processed_tasks": job.processed_tasks,
        "failed_tasks": job.failed_tasks,
        "error_json": job.error_json,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _release_dict(release):
    return {
        "release_id": release.release_id,
        "health": release.health.value,
        "reason": release.reason,
        "updated_at": release.updated_at,
        "execution_allowed": release.health not in {ReleaseHealth.QUARANTINED, ReleaseHealth.RETIRED},
    }


def _session_dict(session):
    return {
        "session_id": session.session_id,
        "account_label": session.account_label,
        "reference_configured": bool(session.credential_ref),
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


def _retention_dict(result):
    return {
        "cutoff": result.cutoff,
        "matched_tasks": result.matched_tasks,
        "deleted_tasks": result.deleted_tasks,
        "dry_run": result.dry_run,
    }


def _engagement_dict(item):
    return {
        "observation_id": item.observation_id,
        "tweet_id": item.tweet_id,
        "task_id": item.task_id,
        "captured_at": item.captured_at,
        "reply_count": item.reply_count,
        "repost_count": item.repost_count,
        "like_count": item.like_count,
        "quote_count": item.quote_count,
        "bookmark_count": item.bookmark_count,
        "view_count": item.view_count,
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    global STATE
    load_env_file(ROOT / ".env")
    config = load_app_config(ROOT, argv)
    logging_settings = configure_logging(config=config, component="web")
    STATE = LiveAppState(config)

    server = ThreadingHTTPServer((config.host, config.port), LiveAppHandler)
    print(f"X ingestion live app running at http://{config.host}:{config.port}")
    print(f"SQLite task ledger: {config.sqlite_path}")
    print(f"Raw evidence directory: {config.raw_evidence_dir}")
    print(f"Log file: {logging_settings.log_file}")
    print("Press Ctrl+C to stop.")
    LOGGER.info(
        "web starting host=%s port=%s sqlite=%s raw_evidence=%s",
        config.host,
        config.port,
        config.sqlite_path,
        config.raw_evidence_dir,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        LOGGER.info("web stopped by keyboard interrupt")
    finally:
        server.server_close()
        LOGGER.info("web server closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
