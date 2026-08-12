# Deployment Runbook

This runbook covers the current no-Docker deployment shape.

## Required Environment

Create `.env` beside `run_app.py`.

```env
X_AUTH_TOKEN=
X_CT0=
X_BEARER=
XINGESTION_DATA_DIR=F:\x-scraper-data
XINGESTION_HOST=127.0.0.1
XINGESTION_PORT=8000
XINGESTION_RETENTION_DAYS=30
XINGESTION_SESSION_ID=local-env-session
XINGESTION_ACCOUNT_LABEL=local-env
XINGESTION_CREDENTIAL_REF=env:X_AUTH_TOKEN,X_CT0,X_BEARER
XINGESTION_SECRET_PROVIDER=env
XINGESTION_SECRET_DIR=
XINGESTION_SESSION_REGISTRY=
XINGESTION_NETWORK_CONTEXT=direct
XINGESTION_WORKER_NETWORK_CONTEXT=
XINGESTION_REQUIRE_MIGRATIONS=true
XINGESTION_MAX_ACTIVE_TASKS_PER_CAPABILITY=100
XINGESTION_LOG_DIR=
XINGESTION_LOG_LEVEL=INFO
XINGESTION_LOG_MAX_BYTES=5242880
XINGESTION_LOG_BACKUP_COUNT=5
```

Use a persistent disk for `XINGESTION_DATA_DIR`. Do not use the build checkout as production storage.

For deployment-mounted secrets, set:

```env
XINGESTION_SECRET_PROVIDER=file
XINGESTION_SECRET_DIR=F:\x-scraper-secrets
XINGESTION_CREDENTIAL_REF=file:session-a
```

Then create `F:\x-scraper-secrets\session-a.json` outside git:

```json
{
  "auth_token": "...",
  "ct0": "...",
  "bearer_token": "..."
}
```

Preflight exposes only provider status and missing field names. It does not print token values.

For multiple authorized sessions, create a registry file outside git:

```json
{
  "sessions": [
    {
      "session_id": "session-a",
      "account_label": "authorized-account-a",
      "credential_ref": "file:session-a",
      "network_context": "proxy:pool-a:iad",
      "health": "HEALTHY"
    },
    {
      "session_id": "session-b",
      "account_label": "authorized-account-b",
      "credential_ref": "file:session-b",
      "network_context": "direct:sfo",
      "health": "DISABLED"
    }
  ]
}
```

`network_context` is parsed as `kind[:route][:region]`; supported kinds are `direct`, `proxy`, and `vpn`. Set `XINGESTION_WORKER_NETWORK_CONTEXT` on a deployed worker to bind it to a route or pool, such as `proxy:pool-a` or `direct:sfo`. The worker will only lease sessions that match the requested kind plus any supplied route/region.

Point the app at it:

```env
XINGESTION_SESSION_REGISTRY=F:\x-scraper-secrets\sessions.json
```

Import or inspect the session inventory:

```powershell
python .\run_sessions.py --import-registry F:\x-scraper-secrets\sessions.json --json
python .\run_sessions.py --json
```

The web console can run the same configured import through:

```text
POST /api/sessions/import
```

The `POST` route is available from the trusted console without an admin-token header. Import output shows session IDs, account labels, network contexts, health, and reference schemes; it does not return `credential_ref` values.

## Start

Apply migrations first:

```powershell
python .\run_migrations.py
python .\run_startup_check.py
python .\run_preflight.py
python .\run_health_report.py
```

Terminal 1:

```powershell
python .\run_app.py --host 0.0.0.0 --port 8000
```

Terminal 2:

```powershell
python .\run_worker.py
```

After the web process is listening, verify the deployed API shape:

```powershell
python .\run_startup_check.py
python .\run_preflight.py --base-url http://127.0.0.1:8000
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000
python .\run_health_report.py --base-url http://127.0.0.1:8000
```

## Health Checks

```text
GET /api/health
GET /api/startup
GET /api/storage
GET /api/metrics
GET /api/migrations
GET /api/telemetry
GET /api/network-health
GET /api/sessions
GET /api/releases
GET /api/releases/current
GET /api/releases/current/risk
```

For supervised hosts, run:

```powershell
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes --require-external-data-dir
```

This fails if the API is not returning JSON, startup directories are not writable, migrations are pending, storage is still inside the checkout, no healthy session exists, a required network route has no healthy matching session, a network route exceeds the configured failure-rate threshold after enough attempts, the release is blocked, outbox lag/depth exceeds thresholds, or the expected web/worker command lines are missing.

For route-bound workers, pass the same route the worker uses:

```powershell
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes --required-network-context proxy:pool-a --max-network-failure-rate 0.8 --min-network-attempts 5
```

`GET /api/releases/current/risk`, `GET /api/network-health`, health reports, and the frontend Network Health panel all keep route remediation separate from release quarantine. If the action is `NETWORK_REMEDIATION_RECOMMENDED`, rotate or pause the affected session/proxy/VPN route first; quarantine the release only when release-level protocol drift signals such as repeated operation or parser failures are present.

The app stores:

- task ledger: `XINGESTION_DATA_DIR\tasks.sqlite3`
- raw evidence: `XINGESTION_DATA_DIR\raw_evidence`
- canonical tweets and observations: `tasks.sqlite3`
- health report exports: `XINGESTION_DATA_DIR\reports\health-report-*.json`
- rotating logs: `XINGESTION_DATA_DIR\logs`

Session records expose `health`, lease metadata, `network_context`, parsed network policy, `cooldown_until`, attempt counters, last attempt/success times, and the latest error class/message. HTTP 429 protocol responses cool down only the leased session, so other healthy sessions can continue processing while the limited account waits. Once the cooldown expires, a successful retry restores that session to `HEALTHY`.

## Submit Work

```http
POST /api/capability-tasks
Content-Type: application/json

{
  "capability_id": "SEARCH_TWEETS",
  "contract_version": 1,
  "payload": {
    "query": "india lang:en",
    "product": "Top",
    "page_size": 20
  },
  "idempotency_key": "client-request-001"
}
```

Poll `status_url` until the task is `DONE`, then read `result_url`.

## Operator Controls

Operator `POST` routes are trusted-console routes and do not require an admin-token header.

Cancel pending work:

```text
POST /api/tasks/{task_id}/cancel
```

Replay failed work:

```text
POST /api/tasks/{task_id}/replay
```

Quarantine a suspect protocol release:

```text
POST /api/releases/current/quarantine
```

Reactivate it after investigation:

```text
POST /api/releases/current/activate
```

List and approve staged protocol manifests:

```powershell
python .\run_releases.py --json
python .\run_releases.py current --json
python .\run_releases.py check xrev-search-tweets-2026-08-10-candidate-1 --json
python .\run_releases.py approve xrev-search-tweets-2026-08-10-candidate-1 --reason operator_approved --json
python .\run_releases.py audits --json
python .\run_releases.py audit promotion-...json --json
```

Equivalent trusted-console routes:

```text
GET /api/releases
POST /api/releases/approve
GET /api/releases/audits
GET /api/releases/audits/{name}
```

Release approval first runs promotion safety checks: manifest presence, release health, binding presence, checked-in fixture validation, and browser-capture/direct-replay comparison when pairs exist. A failed safety report blocks normal approval; use `--force` or `force: true` only for an explicit emergency override. Release approval updates `approved_protocol_release` in SQLite and reloads the live process planner/worker so new tasks use the exact approved manifest. With more than one manifest in `protocol_releases`, startup requires this pointer to be present and resolvable.

Every `run_releases.py check`, normal approval, blocked approval, and force approval writes a redacted `RELEASE_PROMOTION_AUDIT` package under `XINGESTION_DATA_DIR\release_promotions` by default. The package records the release ID, exact manifest path, approval pointer before/after, promotion safety report, force flag, and operator reason without raw X secrets or raw evidence bodies. Detail reads accept only `promotion-*.json` file names from that directory; they do not accept arbitrary paths.

Review advisory release-risk recommendations:

```text
GET /api/releases/current/risk
```

Restore a fixed session to worker rotation:

```text
POST /api/sessions/{session_id}/restore
```

Disable a session without deleting its metadata:

```text
POST /api/sessions/{session_id}/disable
```

Reprocess stored raw evidence without recollecting:

```text
POST /api/tasks/{task_id}/reprocess
```

Build a protocol drift investigation package:

```text
POST /api/tasks/{task_id}/investigate
```

Write a safe failed-task support package from the web API:

```text
POST /api/tasks/{task_id}/export
```

Export a failed-task support package without requiring a running web API:

```powershell
python .\run_failed_task_export.py <task_id>
```

The package is written to `XINGESTION_DATA_DIR\support_exports` by default. It includes runtime error classification, release/session/telemetry context, and raw evidence references, but not raw X secrets or raw evidence bodies. The Needs Attention panel exposes this export for failed tasks and shows the saved path plus redaction metadata.

List and retain generated support exports:

```text
GET /api/support-exports
GET /api/support-exports/{file_name}
GET /api/support-exports/{file_name}/download
POST /api/support-exports/retention
```

The Support Exports panel uses the same endpoints. Detail reads and downloads accept only `failed-task-*.json` file names from `XINGESTION_DATA_DIR\support_exports`; they do not accept arbitrary paths. Downloads return attachment headers. Retention uses `XINGESTION_RETENTION_DAYS` and deletes only `failed-task-*.json` files inside that directory.

List failed and retryable tasks with recommended next actions:

```powershell
python .\run_task_actions.py
python .\run_task_actions.py --json
```

The web console mirrors this in the Needs Attention panel. Parent/operator tooling can read the same JSON at:

```text
GET /api/task-actions
```

Inspect transactional outbox lag and the oldest unpublished events:

```powershell
python .\run_outbox.py --json
```

Process a bounded batch through the same local worker path used in deployment:

```powershell
python .\run_outbox.py --process --limit 5 --json
```

Equivalent web API routes:

```text
GET /api/outbox
POST /api/outbox/process
```

The `POST` route does not require an admin-token header. Processing does not delete rows or manually force acknowledgements; it claims events via the ledger and executes `LocalWorker.process_one()`, so release quarantine, session availability, retry scheduling, telemetry, canonical persistence, and continuation queueing all stay active.

Validate the pinned `SEARCH_TWEETS` parser before and after protocol changes:

```powershell
python .\run_protocol_validation.py --fixtures-only --json
python .\run_protocol_validation.py --raw-only --json
python .\run_protocol_validation.py --raw-only --write --json
python .\run_protocol_validation.py --compare-captures --json
```

The first command checks committed GraphQL regression fixtures. The second checks local captured payloads under `XINGESTION_DATA_DIR\raw_evidence`. The comparison command replays recent replayable browser captures through the approved release recipe, stores linked `direct_replay` evidence in the same raw evidence directory, and compares parser success plus structural/typename fingerprints. Live timeline tweet counts can change between capture and replay, so counts and engagement coverage are reported as observations instead of hard drift failures. The report includes parsed tweet counts, engagement metric coverage, bottom-cursor presence, and stable fingerprints to compare when X changes the response shape. The web console mirrors the read-only combined view and the replay-writing operator run at:

```text
GET /api/protocol-validation
GET /api/protocol-validation/reports
POST /api/protocol-validation/run
```

Saved reports are written to `XINGESTION_DATA_DIR\protocol_validation`. The `POST` route does not require an admin-token header and runs direct replays for recent replayable captures before writing the validation response.

Bulk reprocess completed tasks for a release:

```text
POST /api/reprocess/jobs
```

Run terminal-task retention cleanup:

```text
POST /api/retention/run
```

Export an operator handoff report:

```powershell
python .\run_health_report.py --base-url http://127.0.0.1:8000
```

The report includes preflight checks, migration state, storage paths, task and outbox counts, canonical counts, telemetry summary, release risk, and safe session diagnostics. It intentionally excludes raw X secrets, credential references, and lease tokens.
The `runtime_errors` section groups recent task failures by class, severity, scope, and recommended operator action.

## Verification Before Release

Run locally:

```powershell
python -m unittest discover -s tests
python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py run_outbox.py run_protocol_validation.py run_sessions.py run_releases.py
```

After starting web and worker:

```powershell
python .\run_startup_check.py
python .\run_preflight.py --base-url http://127.0.0.1:8000
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes
python .\run_smoke.py --base-url http://127.0.0.1:8000
python .\run_smoke.py --base-url http://127.0.0.1:8000 --submit "india lang:en" --wait 90
python .\run_health_report.py --base-url http://127.0.0.1:8000
```

CI runs the same checks on Windows Python 3.11 and 3.12, including frontend and secret-hygiene checks.

See [process_supervision.md](process_supervision.md) for Windows Task Scheduler/NSSM examples and restart verification.
See [logging.md](logging.md) for rotating log file configuration.
