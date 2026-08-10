# Worklog

This log records completed, non-broken checkpoints while rebuilding toward `FINAL_PRODUCT_SPEC.md`.

## 2026-08-10 - Checkpoint 1: Protocol Foundation

Implemented:

- Moved the historical scraper scripts, `.env.example`, research notes, and local artifacts into `playground/`.
- Added immutable protocol revision dataclasses for X-rev style recipe composition.
- Added deterministic content hashing for revisions and acquisition recipes.
- Added a candidate `SEARCH_TWEETS` protocol release manifest based on the observed SearchTimeline POST recipe.
- Added standard-library unit tests for immutability, composition hashing, and manifest loading.

Verified:

- `python -m unittest discover -s tests`

Next:

- Extract the current SearchTimeline request builder, parser, and pagination logic from `playground/graphql_search.py` into tested `src/xrev` runtime modules.

## 2026-08-10 - Checkpoint 2: SearchTweets Runtime Extraction

Implemented:

- Added `src/xrev/runtime/search_tweets.py` with typed request, auth, HTTP request, tweet record, and page result objects.
- Added recipe-driven SearchTimeline request construction using the candidate manifest operation and feature bundle.
- Added parser and pagination extraction for protocol-normalized tweet records and opaque bottom cursors.
- Added tests for request construction, pre-network validation, tweet parsing, media extraction, and cursor extraction.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests`

Next:

- Add a raw evidence sink boundary so runtime parsing can refer to durable response evidence before normalization.

## 2026-08-10 - Checkpoint 3: Raw Evidence Boundary

Implemented:

- Added `src/xrev/evidence` with a `RawEvidenceSink` protocol, `RawEvidenceRef`, and local `FileRawEvidenceSink`.
- Stored raw JSON responses with SHA-256 content hashes and sidecar metadata.
- Updated SearchTweets parsing results so parsed pages can carry the raw evidence reference used to produce them.
- Added tests for raw JSON persistence, metadata persistence, content hashing, and parser evidence reference propagation.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests`

Next:

- Add a one-attempt transport boundary that executes a prepared protocol HTTP request and persists raw evidence before parsing.

## 2026-08-10 - Checkpoint 4: One-Attempt Acquisition Boundary

Implemented:

- Added `src/xrev/runtime/transport.py` with a one-attempt transport protocol, typed HTTP response, typed protocol errors, and retry disposition metadata.
- Added `acquire_search_tweets_page(...)` to build the pinned protocol request, call transport exactly once, store raw evidence on success, and parse with the resulting evidence ref.
- Added typed error mapping for auth/session rejection, stale operation IDs, rate limits, upstream server failures, and unexpected statuses.
- Added tests proving success uses one transport call, persists evidence before returning parsed output, and does not hide internal retries for HTTP errors.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests`

Next:

- Add a production-facing capability request/planner shell that maps `SEARCH_TWEETS` capability requests to the pinned candidate recipe without exposing GraphQL internals.
