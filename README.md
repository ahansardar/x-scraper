# X Protocol Ingestion

This repository is being rebuilt from `FINAL_PRODUCT_SPEC.md` into a production-oriented X protocol ingestion platform.

The original GraphQL scripts and local research artifacts now live under `playground/`. They remain useful as an experimental reference, but new production code should follow the spec's split:

- `src/xrev/`: X protocol research/runtime models and validated protocol releases.
- `protocol_releases/`: approved or candidate protocol release manifests.
- `docs/WORKLOG.md`: incremental implementation ledger.

## Current Checkpoint

The current checkpoint defines immutable protocol revision models, a live `SEARCH_TWEETS` capability path, raw evidence persistence, a one-attempt transport boundary, a production-facing capability planner, a durable SQLite task ledger, transactional outbox events, worker leases with renewal, and a local worker dispatcher.

## Verify

```powershell
python -m unittest discover -s tests
python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py
```

GitHub Actions also runs these checks on Windows for Python 3.11 and 3.12.

## Run Local Live App

No Docker is required.

Terminal 1, web app:

```powershell
python .\run_migrations.py
python .\run_app.py --host 127.0.0.1 --port 8000
```

Terminal 2, worker:

```powershell
python .\run_worker.py
```

Open `http://127.0.0.1:8000` and run a live `SEARCH_TWEETS` acquisition. The web app queues a task and the worker processes it from the transactional outbox. The app loads authorized X web session values from `.env`, writes task state to `data/tasks.sqlite3`, and stores raw evidence under `data/raw_evidence/`.

Smoke-check a running deployment:

```powershell
python .\run_smoke.py --base-url http://127.0.0.1:8000
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
    "page_size": 20
  },
  "idempotency_key": "client-request-001"
}
```

The search-specific `POST /api/search-tweets` route remains as a UI compatibility shortcut.

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
XINGESTION_NETWORK_CONTEXT=direct
XINGESTION_ADMIN_TOKEN=
```

Storage locations:

- Default task ledger: `./data/tasks.sqlite3`
- Default raw evidence: `./data/raw_evidence/`
- Production/deployment override: set `XINGESTION_DATA_DIR` to a persistent disk path.

The live app also exposes storage paths at:

```text
GET /api/storage
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
```

The response includes task state counts, active/terminal totals, outbox pending depth and lag, canonical record counts, auth readiness, and storage paths.

Protocol release health is operator-controlled:

```text
GET /api/releases/current
POST /api/releases/current/quarantine
POST /api/releases/current/activate
```

A quarantined release is not executed by the worker; queued work is moved to `DEAD_LETTER` with a `PROTOCOL_RELEASE_BLOCKED` error.

Session metadata is stored without raw secrets in `session_artifacts`. The default local session points to the `.env` variables by reference. Inspect it at:

```text
GET /api/sessions
```

For deployment, point `XINGESTION_DATA_DIR` at persistent storage. Do not use an ephemeral build directory for this value.

See [docs/deployment_runbook.md](docs/deployment_runbook.md) for the no-Docker deployment checklist, health checks, storage paths, operator controls, and release verification commands.

Set `XINGESTION_ADMIN_TOKEN` in deployment. Operator `POST` routes require it in the `x-admin-token` header:

- `POST /api/tasks/{task_id}/cancel`
- `POST /api/tasks/{task_id}/replay`
- `POST /api/retention/run`
- `POST /api/releases/current/quarantine`
- `POST /api/releases/current/activate`

Retention cleanup is available from the Operations panel and:

```text
GET /api/retention
POST /api/retention/run
```

Cleanup removes old `DONE` and `CANCELLED` task ledger rows after `XINGESTION_RETENTION_DAYS`. `DEAD_LETTER` rows are preserved for investigation and replay.
