# X Protocol Ingestion

This repository is being rebuilt from `FINAL_PRODUCT_SPEC.md` into a production-oriented X protocol ingestion platform.

The original GraphQL scripts and local research artifacts now live under `playground/`. They remain useful as an experimental reference, but new production code should follow the spec's split:

- `src/xrev/`: X protocol research/runtime models and validated protocol releases.
- `protocol_releases/`: approved or candidate protocol release manifests.
- `docs/WORKLOG.md`: incremental implementation ledger.

## Current Checkpoint

The current checkpoint defines immutable protocol revision models, a `SEARCH_TWEETS` capability binding for the observed SearchTimeline GraphQL recipe, and tested runtime helpers for building SearchTimeline HTTP requests and parsing response pages. It does not perform live network acquisition yet.

## Verify

```powershell
python -m unittest discover -s tests
```
