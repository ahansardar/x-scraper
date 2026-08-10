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

## 2026-08-10 - Checkpoint 5: Capability Planner Shell

Implemented:

- Added `src/xingestion/capabilities` as the first production control-plane package.
- Added stable `CapabilityRequest`, `SearchTweetsInput`, and `AcquisitionPlan` objects.
- Added `CapabilityPlanner` that maps a stable `SEARCH_TWEETS` request to the pinned protocol binding and recipe.
- Kept GraphQL internals out of public request/plan dictionaries while preserving the internal binding for execution.
- Added tests for planning, request validation, manifest eligibility, and GraphQL detail hiding.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests`

Next:

- Add a minimal durable task ledger interface and SQLite-backed implementation for capability tasks before introducing Redis or worker leases.

## 2026-08-10 - Checkpoint 6: Durable Task Ledger

Implemented:

- Added `src/xingestion/tasks` with task states matching the production lifecycle vocabulary.
- Added `TaskLedger` protocol and `SQLiteTaskLedger` local durable implementation.
- Added idempotent task creation keyed by `idempotency_key`.
- Added fenced-style state transitions that require the expected current state.
- Persisted public capability request and acquisition plan JSON without GraphQL internals.
- Added tests for create/reload durability, idempotency, and guarded transitions.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests`

Next:

- Add a transactional outbox table beside the task ledger so task creation and publish intent can commit atomically.

## 2026-08-10 - Checkpoint 7: Runnable Local Frontend

Implemented:

- Added `run_app.py` and `src/xingestion/web/live_server.py` using only Python standard library HTTP serving.
- Added a `SEARCH_TWEETS` acquisition endpoint that plans the capability request, creates a durable task, stores raw evidence, parses output, and marks the task `DONE`.
- Added a static frontend console for capability input, execution flow, latest parsed output, and task ledger state.
- Added ignored local `data/` storage for SQLite task state and raw evidence.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests`
- Local server smoke test with `python .\run_app.py --port 8000`
- Live `SEARCH_TWEETS` API call returned a `DONE` task, real parsed records, and raw evidence.

Next:

- Add transactional outbox support beside task creation so publish intent is durable before introducing worker dispatch.

## 2026-08-10 - Checkpoint 8: Remove Mock Data and Use Live X Transport

Implemented:

- Removed the local mock SearchTweets transport from the web console path.
- Added `.env` loading and real authorized X web-session auth resolution.
- Added `UrllibJsonTransport` for one-attempt live JSON HTTP calls without adding dependencies.
- Updated the web console health and acquisition flow to report live auth/protocol status.
- Kept raw evidence persistence and durable task state in the live path.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py`

## 2026-08-10 - Checkpoint 9: Remove Demo Naming

Implemented:

- Renamed the runnable entrypoint from `run_demo.py` to `run_app.py`.
- Renamed the web server module from `demo_server.py` to `live_server.py`.
- Replaced remaining live app code paths that used demo naming.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py`

## 2026-08-10 - Checkpoint 10: CI Testers

Implemented:

- Added `.github/workflows/ci.yml`.
- CI runs on push, pull request, and manual dispatch.
- CI uses Windows runners with Python 3.11 and 3.12.
- CI runs unit tests, compile checks, and a frontend asset smoke check.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py`

## 2026-08-10 - Checkpoint 11: Engagement Metric Parsing

Implemented:

- Updated SearchTweets parsing to merge duplicate tweet entries instead of keeping only the first copy.
- Preserved richer engagement metrics when a later duplicate entry includes likes, reposts, replies, quotes, bookmarks, or views.
- Changed missing view counts from blank strings to explicit unavailable state in the frontend.
- Added parser tests for duplicate engagement metric enrichment.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py`
- Live `SEARCH_TWEETS` API call returned populated likes, reposts, replies, quotes, bookmarks, and views.

## 2026-08-10 - Checkpoint 12: Transactional Outbox and Local Worker

Implemented:

- Added `outbox_events` beside `capability_tasks`.
- Task creation now commits task state and publish intent in one SQLite transaction.
- Added outbox claiming for the oldest unpublished event.
- Added `LocalWorker` that claims one event, transitions `CREATED -> ENQUEUED -> RUNNING -> DONE`, stores raw evidence, and handles dead-letter failures.
- Updated the live web app to submit tasks through the outbox/worker path instead of executing acquisition directly in the HTTP handler.
- Added tests for atomic outbox creation, idempotency without duplicate events, event claiming, and local worker completion.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py`

## 2026-08-10 - Checkpoint 13: Deployment Storage Configuration

Implemented:

- Added root `.env.example` for live/deployment settings.
- Added `XINGESTION_DATA_DIR`, `XINGESTION_HOST`, and `XINGESTION_PORT`.
- Added deployment config loader with resolved storage paths.
- Replaced hard-coded `./data` access in the live server with configurable persistent storage.
- Added `/api/storage` and included storage paths in `/api/health`.
- Updated README with exact default storage locations and deployment override guidance.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py`
- Live `/api/storage` reports SQLite and raw evidence locations.

## 2026-08-10 - Checkpoint 14: Split Worker From Web Request

Implemented:

- Added task `result_json` and `error_json` persistence.
- Worker stores raw evidence references on completed tasks.
- Web `POST /api/search-tweets` now queues a task and returns `202` with status/result URLs.
- Added `GET /api/tasks/{task_id}` and `GET /api/tasks/{task_id}/result`.
- Added `run_worker.py` for a separate no-Docker worker process.
- Updated frontend polling to wait for the worker result.
- Updated README with separate web and worker commands.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`

## 2026-08-10 - Checkpoint 15: Durable Retry Scheduling

Implemented:

- Added `attempt_count`, `max_attempts`, and `next_attempt_at` to tasks.
- Worker now increments attempts only when a protocol attempt starts.
- Retryable protocol errors move tasks to `RETRY_SCHEDULED` instead of `DEAD_LETTER`.
- Due retry tasks are re-enqueued with a fresh outbox event.
- Non-retryable or exhausted tasks still move to `DEAD_LETTER`.
- Task API now exposes attempt and next retry metadata.
- Added tests for retry scheduling and due retry re-enqueueing.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`

## 2026-08-10 - Checkpoint 16: Worker Lease Fencing

Implemented:

- Added `lease_owner`, `lease_token`, `lease_expires_at`, and `delivery_generation` to tasks.
- Worker now acquires an execution lease before moving work to `RUNNING`.
- Completion, retry scheduling, and dead-letter writes are fenced by lease token and delivery generation.
- Expired `RUNNING` leases can be recovered to `ENQUEUED` with a fresh outbox event.
- Worker checks for due retries and expired leases before claiming new work.
- Task API exposes lease owner, lease expiry, and delivery generation.
- Added tests for lease acquisition, stale-token rejection, and expired lease recovery.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`
- Live local server health reports auth readiness from `.env`.

Next:

- Add an operator replay path for dead-letter tasks.

## 2026-08-10 - Checkpoint 17: Dead-Letter Replay

Implemented:

- Added durable replay lineage with `replay_origin_task_id` on capability tasks.
- Added `SQLiteTaskLedger.replay_task(...)` that only redrives `DEAD_LETTER` tasks.
- Replay creates a fresh task and transactional outbox event without mutating the failed origin task.
- Added `POST /api/tasks/{task_id}/replay` for deployment/operator use.
- Added frontend replay controls in the task ledger for failed tasks.
- Added tests for replay guardrails, lineage, outbox creation, and worker processing.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`

Next:

- Add task cancellation and retention controls for long-running deployments.

## 2026-08-10 - Checkpoint 18: Task Cancellation

Implemented:

- Added explicit `CANCELLED` terminal state for pre-execution tasks.
- Added `SQLiteTaskLedger.cancel_task(...)` for `CREATED`, `ENQUEUED`, and `RETRY_SCHEDULED` work.
- Added `POST /api/tasks/{task_id}/cancel` for operator control.
- Added frontend Cancel controls for cancellable task states.
- Added tests proving cancelled work is skipped by the worker and cannot be transitioned normally.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`

Next:

- Add retention cleanup controls for terminal deployment data.

## 2026-08-10 - Checkpoint 19: Retention Cleanup

Implemented:

- Added `XINGESTION_RETENTION_DAYS` deployment configuration.
- Added dry-run and apply retention cleanup for old `DONE` and `CANCELLED` tasks.
- Preserved `DEAD_LETTER` tasks for investigation and replay.
- Added `GET /api/retention` and `POST /api/retention/run`.
- Added an Operations frontend panel for retention status and cleanup.
- Documented retention behavior in README.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`

Next:

- Add canonical tweet and engagement observation persistence.

## 2026-08-10 - Checkpoint 20: Canonical Tweet Persistence

Implemented:

- Added canonical SQLite tables for tweet identity and engagement observations.
- Added `CanonicalStore` to upsert tweet entities and append metric observations.
- Worker now persists canonical output after raw evidence is stored and parsed.
- Added `GET /api/canonical/tweets` for canonical counts and latest observations.
- Documented canonical table locations and API inspection route.
- Added tests for canonical ingestion, repeat observations, and worker integration.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`

Next:

- Add operational metrics for tasks, outbox, canonical records, and worker health.

## 2026-08-10 - Checkpoint 21: Operational Metrics

Implemented:

- Added task state counts across all lifecycle states.
- Added outbox pending depth and oldest unpublished event lag.
- Added `GET /api/metrics` with task, outbox, canonical, auth, release, and storage metrics.
- Added a frontend Metrics panel for active tasks, terminal tasks, outbox backlog, canonical tweets, observations, and auth state.
- Documented the metrics endpoint.
- Added tests for metric aggregation and frontend exposure.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`

Next:

- Add session/secret/network allocation primitives before expanding capability coverage.

## 2026-08-10 - Checkpoint 22: Session Metadata Plane

Implemented:

- Added a session artifact registry with account label, credential reference, network context, health, and lease metadata.
- Added guarded session leasing and release without storing raw X secrets.
- Bootstrapped a default deployment session from non-secret `.env` references.
- Added `GET /api/sessions` and included session counts in `/api/metrics`.
- Documented session metadata configuration and inspection.
- Added tests for secret-reference enforcement and session leasing.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`

Next:

- Add protocol release health and quarantine controls.

## 2026-08-10 - Checkpoint 23: Protocol Release Health

Implemented:

- Added durable protocol release health records.
- Added active/quarantined release execution gating in the worker.
- Added `GET /api/releases/current`, quarantine, and activate endpoints.
- Included release health in `/api/metrics`.
- Documented release quarantine behavior.
- Added tests for release health storage and quarantined worker blocking.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`

Next:

- Add a generic northbound capability task API.

## 2026-08-10 - Checkpoint 24: Northbound Capability API

Implemented:

- Added stable `POST /api/capability-tasks` for parent-system task submission.
- Kept `POST /api/search-tweets` as a compatibility shortcut.
- Validated capability ID, contract version, payload shape, and unsupported capabilities.
- Returned the same task, status URL, and result URL contract as the UI route.
- Documented the parent-system request shape.
- Added handler-level tests for generic task submission and rejection.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`

Next:

- Add deployment runbook and CI hardening checks.

## 2026-08-10 - Checkpoint 25: Deployment Runbook and CI Hardening

Implemented:

- Added a no-Docker deployment runbook with environment, start commands, health checks, storage paths, task submission, operator controls, and verification commands.
- Added a secret-hygiene unit test scanning tracked text files for raw X auth material patterns.
- Hardened CI frontend checks to require the Metrics panel.
- Hardened CI documentation checks to require the deployment runbook.
- Linked the runbook from README.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`

Next:

- Add authenticated/admin-only controls before exposing this beyond a trusted deployment boundary.

## 2026-08-10 - Checkpoint 26: Admin Operator Protection

Implemented:

- Added `XINGESTION_ADMIN_TOKEN` deployment configuration.
- Required `x-admin-token` for destructive/operator POST routes.
- Blocked operator routes with `503` when the admin token is not configured.
- Added frontend admin-token prompting for cancel, replay, and retention actions.
- Fixed live app startup ordering so session bootstrap reads auth after auth is initialized.
- Documented protected operator routes in README and deployment runbook.
- Added tests for admin-token accept/reject behavior.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py`

Next:

- Add explicit SQLite migrations and a migration runner.
