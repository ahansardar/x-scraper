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
XINGESTION_NETWORK_CONTEXT=direct
XINGESTION_ADMIN_TOKEN=
XINGESTION_REQUIRE_MIGRATIONS=true
XINGESTION_MAX_ACTIVE_TASKS_PER_CAPABILITY=100
XINGESTION_LOG_DIR=
XINGESTION_LOG_LEVEL=INFO
XINGESTION_LOG_MAX_BYTES=5242880
XINGESTION_LOG_BACKUP_COUNT=5
```

Use a persistent disk for `XINGESTION_DATA_DIR`. Do not use the build checkout as production storage.

## Start

Apply migrations first:

```powershell
python .\run_migrations.py
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
python .\run_preflight.py --base-url http://127.0.0.1:8000
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000
python .\run_health_report.py --base-url http://127.0.0.1:8000
```

## Health Checks

```text
GET /api/health
GET /api/storage
GET /api/metrics
GET /api/migrations
GET /api/telemetry
GET /api/sessions
GET /api/releases/current
GET /api/releases/current/risk
```

For supervised hosts, run:

```powershell
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes --require-external-data-dir
```

This fails if the API is not returning JSON, migrations are pending, storage is still inside the checkout, no healthy session exists, the release is blocked, outbox lag/depth exceeds thresholds, or the expected web/worker command lines are missing.

The app stores:

- task ledger: `XINGESTION_DATA_DIR\tasks.sqlite3`
- raw evidence: `XINGESTION_DATA_DIR\raw_evidence`
- canonical tweets and observations: `tasks.sqlite3`
- health report exports: `XINGESTION_DATA_DIR\reports\health-report-*.json`
- rotating logs: `XINGESTION_DATA_DIR\logs`

Session records expose `health`, lease metadata, `cooldown_until`, attempt counters, last attempt/success times, and the latest error class/message. HTTP 429 protocol responses cool down only the leased session, so other healthy sessions can continue processing while the limited account waits. Once the cooldown expires, a successful retry restores that session to `HEALTHY`.

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

All operator `POST` routes require:

```text
x-admin-token: <XINGESTION_ADMIN_TOKEN>
```

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

Export a failed-task support package without requiring a running web API:

```powershell
python .\run_failed_task_export.py <task_id>
```

The package is written to `XINGESTION_DATA_DIR\support_exports` by default. It includes runtime error classification, release/session/telemetry context, and raw evidence references, but not raw X secrets or raw evidence bodies.

List failed and retryable tasks with recommended next actions:

```powershell
python .\run_task_actions.py
python .\run_task_actions.py --json
```

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
python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py
```

After starting web and worker:

```powershell
python .\run_preflight.py --base-url http://127.0.0.1:8000
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes
python .\run_smoke.py --base-url http://127.0.0.1:8000
python .\run_smoke.py --base-url http://127.0.0.1:8000 --submit "india lang:en" --wait 90
python .\run_health_report.py --base-url http://127.0.0.1:8000
```

CI runs the same checks on Windows Python 3.11 and 3.12, including frontend and secret-hygiene checks.

See [process_supervision.md](process_supervision.md) for Windows Task Scheduler/NSSM examples and restart verification.
See [logging.md](logging.md) for rotating log file configuration.
