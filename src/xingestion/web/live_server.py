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
DATA_ROOT = ROOT / "data"
MANIFEST_PATH = ROOT / "protocol_releases" / "search_tweets.candidate.json"


class LiveAppState:
    def __init__(self) -> None:
        load_env_file(ROOT / ".env")
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        self.manifest = ProtocolReleaseManifest.from_file(MANIFEST_PATH)
        self.planner = CapabilityPlanner(self.manifest)
        self.ledger = SQLiteTaskLedger(DATA_ROOT / "tasks.sqlite3")
        self.evidence_sink = FileRawEvidenceSink(DATA_ROOT / "raw_evidence")
        self.transport = UrllibJsonTransport()
        self.auth = web_session_auth_from_env()
        self.worker = LocalWorker(
            ledger=self.ledger,
            manifest=self.manifest,
            auth=self.auth,
            transport=self.transport,
            raw_evidence_sink=self.evidence_sink,
        )


STATE = LiveAppState()


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
                }
            )
        if parsed.path == "/api/tasks":
            return self._json({"tasks": self._list_tasks()})
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
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

        worker_result = _process_until_task_terminal(task.task_id)
        task = STATE.ledger.get_task(task.task_id) or task

        if worker_result and worker_result.error_class:
            return self._json(
                {
                    "task": _task_dict(task),
                    "error": worker_result.error_class,
                    "message": worker_result.message,
                },
                status=502,
            )

        if worker_result and worker_result.raw_evidence_ref:
            page = _load_page_from_evidence(
                worker_result.raw_evidence_ref.storage_uri,
                worker_result.raw_evidence_ref,
            )
            result = {
                "task": _task_dict(task),
                "plan": plan.public_dict(),
                "raw_evidence": {
                    "evidence_id": page.raw_evidence_ref.evidence_id,
                    "content_sha256": page.raw_evidence_ref.content_sha256,
                    "storage_uri": page.raw_evidence_ref.storage_uri,
                },
                "page": {
                    "next_cursor": page.next_cursor,
                    "tweets": [_tweet_dict(tweet) for tweet in page.tweets],
                },
            }
            return self._json(result, status=201)

        return self._json(
            {
                "task": _task_dict(task),
                "message": (worker_result.message if worker_result else None)
                or "Task queued or already processed",
            },
            status=202,
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

        path = DATA_ROOT / "tasks.sqlite3"
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
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]


def _task_dict(task):
    return {
        "task_id": task.task_id,
        "idempotency_key": task.idempotency_key,
        "capability_id": task.capability_id.value,
        "contract_version": task.contract_version,
        "state": task.state.value,
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


def _process_until_task_terminal(task_id, max_events=10):
    last_result = None
    for _ in range(max_events):
        task = STATE.ledger.get_task(task_id)
        if task and task.state in (TaskState.DONE, TaskState.DEAD_LETTER):
            return last_result
        last_result = STATE.worker.process_one()
        if not last_result.processed:
            return last_result
    return last_result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    port = 8000
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])

    server = ThreadingHTTPServer(("127.0.0.1", port), LiveAppHandler)
    print(f"X ingestion live app running at http://127.0.0.1:{port}")
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
