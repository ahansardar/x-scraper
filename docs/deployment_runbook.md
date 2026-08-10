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
```

Use a persistent disk for `XINGESTION_DATA_DIR`. Do not use the build checkout as production storage.

## Start

Apply migrations first:

```powershell
python .\run_migrations.py
```

Terminal 1:

```powershell
python .\run_app.py --host 0.0.0.0 --port 8000
```

Terminal 2:

```powershell
python .\run_worker.py
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
```

The app stores:

- task ledger: `XINGESTION_DATA_DIR\tasks.sqlite3`
- raw evidence: `XINGESTION_DATA_DIR\raw_evidence`
- canonical tweets and observations: `tasks.sqlite3`

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

Reprocess stored raw evidence without recollecting:

```text
POST /api/tasks/{task_id}/reprocess
```

Run terminal-task retention cleanup:

```text
POST /api/retention/run
```

## Verification Before Release

Run locally:

```powershell
python -m unittest discover -s tests
python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py
```

After starting web and worker:

```powershell
python .\run_smoke.py --base-url http://127.0.0.1:8000
python .\run_smoke.py --base-url http://127.0.0.1:8000 --submit "india lang:en" --wait 90
```

CI runs the same checks on Windows Python 3.11 and 3.12, including frontend and secret-hygiene checks.
