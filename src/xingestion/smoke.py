from __future__ import annotations

from dataclasses import dataclass
import json
import time
from urllib import request


@dataclass(frozen=True)
class SmokeResult:
    ok: bool
    messages: tuple[str, ...]


class SmokeClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def run(self, *, submit_query: str | None = None, wait_seconds: int = 60) -> SmokeResult:
        messages: list[str] = []
        health = self._get("/api/health")
        metrics = self._get("/api/metrics")
        storage = self._get("/api/storage")
        release = self._get("/api/releases/current")
        sessions = self._get("/api/sessions")
        messages.append(f"health ok release={health['release_id']} auth_ready={health['auth_ready']}")
        messages.append(f"sqlite={storage['sqlite_path']}")
        messages.append(f"raw_evidence={storage['raw_evidence_dir']}")
        messages.append(f"release_health={release['release']['health']}")
        messages.append(f"sessions={len(sessions['sessions'])}")
        messages.append(
            "metrics active_tasks={active} canonical_tweets={tweets}".format(
                active=metrics["tasks"]["active"],
                tweets=metrics["canonical"]["canonical_tweets"],
            )
        )

        if submit_query:
            task = self._submit(submit_query)
            messages.append(f"submitted task={task['task']['task_id']}")
            result = self._wait_for_result(task["result_url"], wait_seconds=wait_seconds)
            messages.append(
                "result state={state} tweets={count}".format(
                    state=result["task"]["state"],
                    count=len(result["page"]["tweets"]),
                )
            )
            canonical = self._get("/api/canonical/tweets")
            messages.append(
                "canonical tweets={tweets} observations={observations}".format(
                    tweets=canonical["counts"]["canonical_tweets"],
                    observations=canonical["counts"]["engagement_observations"],
                )
            )

        return SmokeResult(ok=True, messages=tuple(messages))

    def _submit(self, query: str) -> dict:
        payload = {
            "capability_id": "SEARCH_TWEETS",
            "contract_version": 1,
            "payload": {
                "query": query,
                "product": "Top",
                "page_size": 20,
            },
            "idempotency_key": f"smoke:{int(time.time())}",
        }
        return self._post("/api/capability-tasks", payload)

    def _wait_for_result(self, result_url: str, *, wait_seconds: int) -> dict:
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                return self._get(result_url)
            except RuntimeError as exc:
                message = str(exc)
                if "HTTP 202" not in message:
                    raise
            time.sleep(2)
        raise TimeoutError(f"Timed out waiting for {result_url}")

    def _get(self, path: str) -> dict:
        return self._send("GET", path)

    def _post(self, path: str, payload: dict) -> dict:
        return self._send("POST", path, payload=payload)

    def _send(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"content-type": "application/json"}
        req = request.Request(url, data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"{method} {url} failed: {exc}") from exc
