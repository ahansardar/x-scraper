# X Protocol Ingestion

This repository is being rebuilt from `FINAL_PRODUCT_SPEC.md` into a production-oriented X protocol ingestion platform.

The original GraphQL scripts and local research artifacts now live under `playground/`. They remain useful as an experimental reference, but new production code now lives under one product package:

- `src/xingestion/`: production ingestion, web, worker, storage, operations, and protocol runtime code.
- `src/xingestion/xprotocol/`: internal X protocol research/runtime models and validated protocol release bindings.
- `protocol_releases/`: approved or candidate protocol release manifests.
- `docs/SYSTEM_FLOW.md`: how the system actually works today, end to end, with diagrams -- start here if you're new.
- `docs/WORKLOG.md`: incremental implementation ledger.
- `docs/TASKS.md`: living checklist of remaining work, with completed items struck through.
- `docs/CURRENT_STAGE.md`: current implementation stage versus `FINAL_PRODUCT_SPEC.md`.

## Current Checkpoint

The current checkpoint defines immutable protocol revision models, a live `SEARCH_TWEETS` capability path, raw evidence persistence, a one-attempt transport boundary, a production-facing capability planner, a PostgreSQL durable task ledger and transactional outbox, Redis Streams delivery, fenced worker leases, and a dedicated dispatcher process.

Track the remaining implementation work in [docs/TASKS.md](docs/TASKS.md). That file uses markdown checkboxes and strikethrough so completed items can be marked as `- [x] ~~done item~~` while open items stay unchecked.

## Verify

```powershell
python -m unittest discover -s tests
python -m compileall -q src tests run_app.py run_worker.py run_dispatcher.py run_migrations.py run_postgres_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py run_outbox.py run_protocol_validation.py run_sessions.py run_releases.py
```

GitHub Actions runs these checks on Windows for Python 3.11 and 3.12, plus a dedicated Ubuntu Postgres/Redis service-container job for Python 3.11 and 3.12.

## Run Local Live App

Docker Compose is used only to start local Postgres and Redis infrastructure. The application itself still runs as plain Python processes: web app, dispatcher, and worker.

Preferred local launcher:

```powershell
.\run_all.ps1
```

That command starts Docker Compose infrastructure, waits for Postgres/Redis health, runs both migration sets, starts the web frontend/backend, dispatcher, and worker, then runs live preflight against the web API. It writes process logs under `data/run_all/logs` and records process IDs in `data/run_all/pids.json`.

Stop the Python processes started by the launcher:

```powershell
.\run_all.ps1 -Stop
```

Use `.\run_all.ps1 -Visible` if you want separate visible PowerShell windows for the web, dispatcher, and worker logs. Use `.\run_all.ps1 -SkipDocker` only when Postgres and Redis are already running.

Manual equivalent:

Terminal 0, infrastructure:

```powershell
docker compose up -d
docker compose ps
python .\run_postgres_migrations.py
python .\run_migrations.py
```

Terminal 1, web app:

```powershell
python .\run_startup_check.py
python .\run_preflight.py
python .\run_app.py --host 127.0.0.1 --port 8000
```

Terminal 2, dispatcher:

```powershell
python .\run_dispatcher.py
```

Terminal 3, worker:

```powershell
python .\run_worker.py
```

Open `http://127.0.0.1:8000` and run a live `SEARCH_TWEETS` acquisition. The web app queues a task in Postgres, the dispatcher publishes the committed outbox row to Redis Streams, and the worker consumes it through the Redis consumer group with a fenced Postgres lease. The app loads authorized X web session values from `.env`, stores durable task/outbox state in Postgres, keeps session/release/canonical/telemetry state in SQLite, and stores raw evidence under `data/raw_evidence/`.

Smoke-check a running deployment:

```powershell
python .\run_startup_check.py
python .\run_preflight.py --base-url http://127.0.0.1:8000
python .\run_smoke.py --base-url http://127.0.0.1:8000
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000
python .\run_health_report.py --base-url http://127.0.0.1:8000
```

Submit one real task and wait for the worker:

```powershell
python .\run_smoke.py --base-url http://127.0.0.1:8000 --submit "india lang:en" --wait 90
```

Parent systems can submit through the stable capability API:

```http
POST /api/capability-tasks
Content-Type: application/json

{
  "capability_id": "SEARCH_TWEETS",
  "contract_version": 1,
  "payload": {
    "query": "india lang:en",
    "product": "Top",
    "page_size": 20,
    "max_pages": 1
  },
  "idempotency_key": "client-request-001"
}
```

The search-specific `POST /api/search-tweets` route remains as a UI compatibility shortcut.

If active task depth for a capability reaches `XINGESTION_MAX_ACTIVE_TASKS_PER_CAPABILITY`, submissions return HTTP `429` before a task is created.

## Deployment Configuration

Create `.env` from `.env.example` and set:

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
XINGESTION_POSTGRES_DSN=postgresql://xingestion:xingestion@127.0.0.1:55432/xingestion
XINGESTION_POSTGRES_POOL_MIN=1
XINGESTION_POSTGRES_POOL_MAX=10
XINGESTION_REDIS_URL=redis://127.0.0.1:6379/0
XINGESTION_REDIS_STREAM=xingestion:capability-tasks
XINGESTION_REDIS_CONSUMER_GROUP=capability-workers
XINGESTION_REDIS_CONSUMER_NAME=
XINGESTION_REDIS_CLAIM_MIN_IDLE_MS=300000
```

Storage locations:

- Default task ledger and transactional outbox: PostgreSQL from `XINGESTION_POSTGRES_DSN`
- Default Redis delivery stream: `XINGESTION_REDIS_STREAM` on `XINGESTION_REDIS_URL`
- Default SQLite operational store: `./data/tasks.sqlite3` for sessions, release approvals, canonical records, telemetry, and reprocess jobs
- Default raw evidence: `./data/raw_evidence/`
- Default health reports: `./data/reports/`
- Default protocol validation reports: `./data/protocol_validation/`
- Default logs: `./data/logs/`

The worker resolves `approved_protocol_release.release_id` from the SQLite operational database and loads the exact matching manifest from `protocol_releases/`. If a checkout contains exactly one manifest and no approved pointer yet exists, startup bootstraps that single release as approved. With multiple manifests, startup fails until an approved release ID is set.

Inspect and approve staged protocol manifests without editing SQLite directly:

```powershell
python .\run_releases.py --json
python .\run_releases.py current --json
python .\run_releases.py check xrev-search-tweets-2026-08-10-candidate-1 --json
python .\run_releases.py approve xrev-search-tweets-2026-08-10-candidate-1 --reason operator_approved --json
```

The live console exposes the same inventory through `GET /api/releases` and can approve a staged manifest through `POST /api/releases/approve`. Approval runs promotion safety checks first: manifest presence, release health, binding presence, checked-in fixture validation, and browser-capture/direct-replay comparison when pairs exist. Use `--force` only for an explicit emergency override. Approval reloads the in-process planner and local worker so new tasks bind to the approved manifest immediately.

Secret providers:

- `XINGESTION_SECRET_PROVIDER=env` resolves `env:X_AUTH_TOKEN,X_CT0,X_BEARER` from environment variables. This is the local fallback.
- `XINGESTION_SECRET_PROVIDER=file` resolves `file:<session-name>` from `XINGESTION_SECRET_DIR\<session-name>.json`. The JSON object must contain `auth_token`, `ct0`, and `bearer_token`.

Do not commit secret files. Mount `XINGESTION_SECRET_DIR` from host-managed storage in deployment.

For multi-session deployments, set `XINGESTION_SESSION_REGISTRY` to a JSON file outside git:

```json
{
  "sessions": [
    {
      "session_id": "session-a",
      "account_label": "authorized-account-a",
      "credential_ref": "file:session-a",
      "network_context": "proxy:pool-a:iad",
      "health": "HEALTHY"
    }
  ]
}
```

`network_context` is validated as `kind[:route][:region]`; supported kinds are `direct`, `proxy`, and `vpn`. `XINGESTION_NETWORK_CONTEXT` sets the default local session network. `XINGESTION_WORKER_NETWORK_CONTEXT` optionally restricts a deployed worker to matching sessions, for example `proxy:pool-a` or `direct:iad`.

Import/list session metadata without printing secret references:

```powershell
python .\run_sessions.py --import-registry F:\x-scraper-secrets\sessions.json --json
python .\run_sessions.py --json
```
- Production/deployment override: set `XINGESTION_DATA_DIR` to a persistent disk path.

The live app also exposes storage paths at:

```text
GET /api/storage
GET /api/startup
GET /api/health
```

Canonical output is stored in the same SQLite database:

- `canonical_tweets`: one row per platform tweet ID.
- `engagement_observations`: append-only metric observations per acquisition.

Inspect the latest canonical counts and observations at:

```text
GET /api/canonical/tweets
```

Operational metrics are exposed at:

```text
GET /api/metrics
GET /api/migrations
GET /api/telemetry
GET /api/network-health
GET /api/releases/current/risk
```

Protocol telemetry is stored append-only in `protocol_attempts` and summarizes successes, failures, network route attribution, and protocol error classes by acquisition attempt. `GET /api/network-health` groups attempts by `network_context`, including success/failure counts, failure rate, distinct session count, latest attempt timestamps, and route-specific error classes.

Release risk recommendations are advisory. Repeated operation or parser drift signals can recommend investigation or quarantine, while repeated route-specific failures recommend network remediation before changing protocol code. Only operator `POST` routes change release health.

The response includes task state counts, active/terminal totals, outbox pending depth and lag, canonical record counts, auth readiness, and storage paths.

Inspect and process unpublished transactional outbox events manually:

```powershell
python .\run_outbox.py --json
python .\run_outbox.py --process --limit 5 --json
```

In normal operation, `run_dispatcher.py` delivers committed Postgres outbox rows to Redis Streams and `run_worker.py` consumes them. The `--process` path is a bounded manual recovery drain that still uses the same worker execution path; it does not delete or force-publish queued events outside worker handling.

Validate the pinned `SEARCH_TWEETS` parser against checked-in protocol fixtures and local raw evidence:

```powershell
python .\run_protocol_validation.py --json
python .\run_protocol_validation.py --fixtures-only --json
python .\run_protocol_validation.py --raw-only --json
python .\run_protocol_validation.py --raw-only --write --json
python .\run_protocol_validation.py --compare-captures --json
```

The report includes parsed tweet counts, engagement coverage, cursor presence, and structural/typename fingerprints for drift comparison. `--compare-captures` replays recent replayable browser captures through the approved release recipe, stores linked `direct_replay` raw evidence, and compares browser-vs-replay parser/shape fingerprints while reporting volatile tweet-count differences as observations. Saved reports are written to `XINGESTION_DATA_DIR\protocol_validation`.

Protocol release health is operator-controlled:

```text
GET /api/releases/current
GET /api/releases
POST /api/releases/current/quarantine
POST /api/releases/current/activate
POST /api/releases/approve
```

A quarantined release is not executed by the worker; queued work is moved to `DEAD_LETTER` with a `PROTOCOL_RELEASE_BLOCKED` error.

Session metadata is stored without raw secrets in `session_artifacts`. The default local session points to the `.env` variables by reference. Inspect it at:

```text
GET /api/sessions
POST /api/sessions/import
POST /api/sessions/{session_id}/restore
POST /api/sessions/{session_id}/disable
```

Workers acquire a healthy session lease before each acquisition attempt and release it after the attempt. If `XINGESTION_WORKER_NETWORK_CONTEXT` is set, the worker only leases sessions whose validated network policy matches that kind/route/region. If no matching healthy session is available, the task is moved to `RETRY_SCHEDULED` without making an X request.

When a session is leased, the worker resolves that session's own credential reference through the configured secret provider. If the reference cannot resolve complete web-session auth, only that session is marked `AUTH_EXPIRED` and the task is scheduled for retry.

Session-scoped protocol errors update session health automatically. Auth/session rejection marks a session `AUTH_EXPIRED`; rate limits mark it `DEGRADED` with a durable `cooldown_until` timestamp. Workers skip cooled-down sessions until the timestamp expires, then allow that degraded session back into rotation for another attempt. A successful cooled-down attempt restores that session to `HEALTHY`.

Each session also stores safe operational attempt visibility: total attempts, successes, failures, last attempt time, last success time, last error class/message, and parsed network policy metadata. These fields are available from `GET /api/sessions` and the Sessions panel.

For deployment, point `XINGESTION_DATA_DIR` at persistent storage. Do not use an ephemeral build directory for this value.

Before exposing a deployment, run:

```powershell
python .\run_startup_check.py
python .\run_preflight.py --base-url http://127.0.0.1:8000
```

Use `--strict-warnings` when auth/API warning states should fail the command in automation.

Export an operator health report after preflight:

```powershell
python .\run_health_report.py --base-url http://127.0.0.1:8000
```

Reports are written to `XINGESTION_DATA_DIR\reports\health-report-*.json` unless `--output` is provided. The JSON includes preflight status, storage paths, migration status, task/outbox counts, canonical counts, telemetry summary, active-release network route health, route remediation recommendations, release risk, and safe session diagnostics. It does not export raw X secrets, credential references, or lease tokens.
Health reports also include a `runtime_errors` section with recent task failures grouped by error class, severity, and scope, plus the recommended operator action.

See [docs/deployment_runbook.md](docs/deployment_runbook.md) for the deployment checklist, local Postgres/Redis infrastructure setup, health checks, storage paths, operator controls, and release verification commands.

For hosted operation, run the web, dispatcher, and worker commands under a process supervisor and verify them with:

```powershell
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes --require-external-data-dir
```

The supervisor also checks `/api/network-health`. Use `--required-network-context proxy:pool-a`, `--max-network-failure-rate 0.8`, and `--min-network-attempts 5` to require a healthy matching route and fail repeatedly unhealthy routes after enough evidence. The release-risk response keeps these as `NETWORK_REMEDIATION_RECOMMENDED` advisories so operators rotate sessions, proxy pools, or VPN paths before quarantining a protocol release.

See [docs/process_supervision.md](docs/process_supervision.md) for Windows Task Scheduler/NSSM setup and restart checks.

Logs use rotating file handlers. Leave `XINGESTION_LOG_DIR` blank to write under `XINGESTION_DATA_DIR\logs`, or set it to a host-managed persistent log directory. See [docs/logging.md](docs/logging.md).
Worker failure logs include the structured runtime error class, severity, scope, retryability, and operator action.

Operator routes are trusted-console routes and do not require an admin-token header:

- `POST /api/tasks/{task_id}/cancel`
- `POST /api/tasks/{task_id}/replay`
- `POST /api/retention/run`
- `POST /api/releases/current/quarantine`
- `POST /api/releases/current/activate`
- `POST /api/tasks/{task_id}/reprocess`
- `POST /api/tasks/{task_id}/investigate`
- `POST /api/tasks/{task_id}/export`
- `GET /api/support-exports/{file_name}/download`
- `POST /api/support-exports/retention`
- `POST /api/outbox/process`
- `POST /api/reprocess/jobs`
- `POST /api/sessions/{session_id}/restore`
- `POST /api/sessions/{session_id}/disable`

Reprocessing parses stored raw evidence again and appends canonical observations without making a new X request.

Investigation packages combine task error state, release and recipe metadata, session diagnostics, telemetry attempts, and raw evidence references:

```text
POST /api/tasks/{task_id}/investigate
```

The web console can also write the same safe failed-task support export from the Needs Attention panel:

```text
POST /api/tasks/{task_id}/export
```

Export a safe failed-task support package directly from local storage:

```powershell
python .\run_failed_task_export.py <task_id>
```

Exports are written to `XINGESTION_DATA_DIR\support_exports\failed-task-*.json` by default. They include task state, runtime-error classification, release/session/telemetry context, and raw evidence references only. The web export response returns the saved path, support summary, and redaction metadata.

The web console lists generated support packages in the Support Exports panel and via:

```text
GET /api/support-exports
GET /api/support-exports/{file_name}
GET /api/support-exports/{file_name}/download
POST /api/support-exports/retention
```

Support export reads and downloads accept only `failed-task-*.json` file names from `XINGESTION_DATA_DIR\support_exports`; callers do not pass arbitrary filesystem paths. Downloads return `Content-Disposition: attachment`. Support export retention uses `XINGESTION_RETENTION_DAYS`, deletes only `failed-task-*.json` files under that directory, and leaves task ledger rows untouched.

List failed and retryable tasks with recommended operator actions:

```powershell
python .\run_task_actions.py
python .\run_task_actions.py --json
```

The web console also exposes the same queue in the Needs Attention panel and via:

```text
GET /api/task-actions
```

Inspect and process the transactional outbox through HTTP:

```text
GET /api/outbox
POST /api/outbox/process
GET /api/protocol-validation
GET /api/protocol-validation/reports
POST /api/protocol-validation/run
```

The Outbox Recovery panel mirrors these endpoints. Processing is bounded by request limit and uses the live worker path, including session leasing, release quarantine checks, telemetry, canonical persistence, retry scheduling, and continuation queueing.

Retention cleanup is available from the Operations panel and:

```text
GET /api/retention
POST /api/retention/run
```

Cleanup removes old `DONE` and `CANCELLED` task ledger rows after `XINGESTION_RETENTION_DAYS`. `DEAD_LETTER` rows are preserved for investigation and replay.
