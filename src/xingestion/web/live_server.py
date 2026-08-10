from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xingestion.capabilities import (
    CapabilityPlanner,
    CapabilityRequest,
    SearchTweetsInput,
)
from xingestion.config import AppConfig, load_app_config
from xingestion.tasks import SQLiteTaskLedger, TaskState
from xingestion.workers import LocalWorker
from xrev.evidence import FileRawEvidenceSink
from xrev.protocol import CapabilityId, ProtocolReleaseManifest
from xrev.runtime import (
    UrllibJsonTransport,
    load_env_file,
    web_session_auth_from_env,
)


STATIC_ROOT = ROOT / "src" / "xingestion" / "web" / "static"
MANIFEST_PATH = ROOT / "protocol_releases" / "search_tweets.candidate.json"


class LiveAppState:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.raw_evidence_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = ProtocolReleaseManifest.from_file(MANIFEST_PATH)
        self.planner = CapabilityPlanner(self.manifest)
        self.ledger = SQLiteTaskLedger(self.config.sqlite_path)
        self.evidence_sink = FileRawEvidenceSink(self.config.raw_evidence_dir)
        self.transport = UrllibJsonTransport()
        self.auth = web_session_auth_from_env()
        self.worker = LocalWorker(
            ledger=self.ledger,
            manifest=self.manifest,
            auth=self.auth,
            transport=self.transport,
            raw_evidence_sink=self.evidence_sink,
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
        if parsed.path == "/api/storage":
            return self._json(_storage_dict())
        if parsed.path == "/api/tasks":
            return self._json({"tasks": self._list_tasks()})
        if parsed.path.startswith("/api/tasks/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 3:
                return self._task_detail(parts[2])
            if len(parts) == 4 and parts[3] == "result":
                return self._task_result(parts[2])
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/tasks/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "replay":
                return self._replay_task(parts[2])

        if parsed.path != "/api/search-tweets":
            self.send_error(404)
            return

        body = self._read_json()
        query = str(body.get("query", "")).strip()
        product = str(body.get("product", "Top"))
        page_size = int(body.get("page_size", 20))
        idempotency_key = str(
            body.get("idempotency_key")
            or f"live:{query}:{product}:{page_size}"
        )

        capability_request = CapabilityRequest(
            capability_id=CapabilityId.SEARCH_TWEETS,
            contract_version=1,
            payload=SearchTweetsInput(
                query=query,
                product=product,
                page_size=page_size,
            ),
        )
        plan = STATE.planner.plan(capability_request)
        task = STATE.ledger.create_task(
            idempotency_key=idempotency_key,
            capability_id=capability_request.capability_id,
            contract_version=capability_request.contract_version,
            request_json=capability_request.public_dict(),
            plan_json=plan.public_dict(),
        )

        return self._json(
            {
                "task": _task_dict(task),
                "message": "Task queued",
                "status_url": f"/api/tasks/{task.task_id}",
                "result_url": f"/api/tasks/{task.task_id}/result",
            },
            status=202,
        )

    def _replay_task(self, task_id):
        try:
            task = STATE.ledger.replay_task(task_id)
        except ValueError as exc:
            status = 404 if "not found" in str(exc).lower() else 409
            return self._json({"message": str(exc)}, status=status)

        return self._json(
            {
                "task": _task_dict(task),
                "message": "Replay task queued",
                "status_url": f"/api/tasks/{task.task_id}",
                "result_url": f"/api/tasks/{task.task_id}/result",
            },
            status=201,
        )

    def _read_json(self):
        length = int(self.headers.get("content-length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

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
    from xrev.runtime import parse_search_tweets_page

    payload = json.loads(Path(storage_uri).read_text(encoding="utf-8"))
    return parse_search_tweets_page(payload, raw_evidence_ref=raw_evidence_ref)


def _raw_evidence_ref_from_json(raw_evidence):
    from xrev.evidence import RawEvidenceRef

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
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    global STATE
    load_env_file(ROOT / ".env")
    config = load_app_config(ROOT, argv)
    STATE = LiveAppState(config)

    server = ThreadingHTTPServer((config.host, config.port), LiveAppHandler)
    print(f"X ingestion live app running at http://{config.host}:{config.port}")
    print(f"SQLite task ledger: {config.sqlite_path}")
    print(f"Raw evidence directory: {config.raw_evidence_dir}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
