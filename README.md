# X Protocol Ingestion

This repository is being rebuilt from `FINAL_PRODUCT_SPEC.md` into a production-oriented X protocol ingestion platform.

The original GraphQL scripts and local research artifacts now live under `playground/`. They remain useful as an experimental reference, but new production code should follow the spec's split:

- `src/xrev/`: X protocol research/runtime models and validated protocol releases.
- `protocol_releases/`: approved or candidate protocol release manifests.
- `docs/WORKLOG.md`: incremental implementation ledger.

## Current Checkpoint

The current checkpoint defines immutable protocol revision models, a `SEARCH_TWEETS` capability binding for the observed SearchTimeline GraphQL recipe, tested runtime helpers, a raw evidence sink boundary, a one-attempt acquisition boundary, a production-facing capability planner shell, and a local durable task ledger. It does not perform live network acquisition yet.

## Verify

```powershell
python -m unittest discover -s tests
```

## Run Local Live App

No Docker is required.

```powershell
python .\run_demo.py --port 8000
```

Open `http://127.0.0.1:8000` and run a live `SEARCH_TWEETS` acquisition. The app loads authorized X web session values from `.env`, writes task state to `data/tasks.sqlite3`, and stores raw evidence under `data/raw_evidence/`.
