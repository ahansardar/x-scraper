# X Protocol Ingestion

This repository is being rebuilt from `FINAL_PRODUCT_SPEC.md` into a production-oriented X protocol ingestion platform.

The original GraphQL scripts and local research artifacts now live under `playground/`. They remain useful as an experimental reference, but new production code should follow the spec's split:

- `src/xrev/`: X protocol research/runtime models and validated protocol releases.
- `protocol_releases/`: approved or candidate protocol release manifests.
- `docs/WORKLOG.md`: incremental implementation ledger.

## Current Checkpoint

The current checkpoint defines immutable protocol revision models, a live `SEARCH_TWEETS` capability path, raw evidence persistence, a one-attempt transport boundary, a production-facing capability planner, a durable SQLite task ledger, transactional outbox events, and a local worker dispatcher.

## Verify

```powershell
python -m unittest discover -s tests
python -m compileall -q src tests run_app.py
```

GitHub Actions also runs these checks on Windows for Python 3.11 and 3.12.

## Run Local Live App

No Docker is required.

```powershell
python .\run_app.py --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` and run a live `SEARCH_TWEETS` acquisition. The app loads authorized X web session values from `.env`, writes task state to `data/tasks.sqlite3`, and stores raw evidence under `data/raw_evidence/`.

## Deployment Configuration

Create `.env` from `.env.example` and set:

```env
X_AUTH_TOKEN=
X_CT0=
X_BEARER=
XINGESTION_DATA_DIR=F:\x-scraper-data
XINGESTION_HOST=127.0.0.1
XINGESTION_PORT=8000
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

For deployment, point `XINGESTION_DATA_DIR` at persistent storage. Do not use an ephemeral build directory for this value.
