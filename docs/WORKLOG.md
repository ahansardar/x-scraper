# Worklog

This log records completed, non-broken checkpoints while rebuilding toward `FINAL_PRODUCT_SPEC.md`.

## 2026-08-10 - Checkpoint 1: Protocol Foundation

Implemented:

- Moved the historical scraper scripts, `.env.example`, research notes, and local artifacts into `playground/`.
- Added immutable protocol revision dataclasses for protocol runtime style recipe composition.
- Added deterministic content hashing for revisions and acquisition recipes.
- Added a candidate `SEARCH_TWEETS` protocol release manifest based on the observed SearchTimeline POST recipe.
- Added standard-library unit tests for immutability, composition hashing, and manifest loading.

Verified:

- `python -m unittest discover -s tests`

Next:

- Extract the current SearchTimeline request builder, parser, and pagination logic from `playground/graphql_search.py` into tested `src/xingestion/xprotocol` runtime modules.

## 2026-08-10 - Checkpoint 2: SearchTweets Runtime Extraction

Implemented:

- Added `src/xingestion/xprotocol/runtime/search_tweets.py` with typed request, auth, HTTP request, tweet record, and page result objects.
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

- Added `src/xingestion/xprotocol/evidence` with a `RawEvidenceSink` protocol, `RawEvidenceRef`, and local `FileRawEvidenceSink`.
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

- Added `src/xingestion/xprotocol/runtime/transport.py` with a one-attempt transport protocol, typed HTTP response, typed protocol errors, and retry disposition metadata.
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

## 2026-08-10 - Checkpoint 27: SQLite Migration Runner

Implemented:

- Added a versioned SQLite migration runner with `schema_migrations`.
- Added baseline SQL for task ledger, outbox, canonical data, sessions, and release health tables.
- Added `run_migrations.py` for no-Docker deployment startup.
- Updated README, deployment runbook, and CI compile checks.
- Added tests proving baseline migrations apply once and create expected tables.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py`

Next:

- Add worker lease heartbeat renewal for long-running attempts.

## 2026-08-10 - Checkpoint 28: Worker Lease Renewal

Implemented:

- Added fenced `renew_execution_lease(...)` on the SQLite task ledger.
- Renewal requires task ID, current lease token, current delivery generation, and `RUNNING` state.
- Worker refreshes the lease before protocol execution and again before completion writes.
- Worker results expose lease renewal counts for diagnostics.
- Added tests for valid lease renewal, stale-token rejection, and worker renewal behavior.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py`

Next:

- Add a local live smoke command for deployment verification.

## 2026-08-10 - Checkpoint 29: Deployment Smoke Command

Implemented:

- Added `run_smoke.py` for no-Docker deployment health verification.
- Smoke checks `/api/health`, `/api/storage`, `/api/metrics`, `/api/sessions`, and `/api/releases/current`.
- Optional `--submit` path posts a real `SEARCH_TWEETS` capability task and polls its result.
- Smoke output reports storage paths, auth readiness, release health, sessions, active tasks, and canonical counts.
- Updated README, deployment runbook, and CI compile checks.
- Added smoke client tests for health-only and real capability submission payload shape.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Add multi-page pagination orchestration with bounded cursor tasks.

## 2026-08-10 - Checkpoint 31: Bounded Pagination Tasks

Implemented:

- Extended `SEARCH_TWEETS` capability payloads with `max_pages`, `page_number`, and pagination lineage fields.
- Worker now creates a new durable continuation task when protocol runtime returns a next cursor and the bounded page limit is not reached.
- Continuation tasks preserve root task ID, parent task ID, opaque cursor, page number, and max page limit.
- Completed task results now include pagination metadata and continuation task ID.
- Generic capability API accepts `max_pages`.
- Added tests for capability validation, northbound payload persistence, continuation queueing, and bounded stop behavior.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Harden migration status and startup validation.

## 2026-08-10 - Checkpoint 32: Migration Status Enforcement

Implemented:

- Added migration status reporting with available, applied, and pending versions.
- Added `require_current()` to fail startup when required migrations are pending.
- Added `XINGESTION_REQUIRE_MIGRATIONS` deployment configuration, defaulting to enabled.
- Live app now validates migrations before initializing stores.
- Added `GET /api/migrations` and included migration status in `/api/metrics`.
- Documented migration enforcement in README and deployment runbook.
- Added tests for pending/current migration status and public-safe status serialization.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Integrate worker session leasing with per-task acquisition.

## 2026-08-10 - Checkpoint 33: Worker Session Leasing

Implemented:

- Worker now acquires a healthy session lease before each acquisition attempt.
- Worker releases the session lease after success or failure.
- Standalone worker bootstraps the default session metadata from deployment config.
- If no healthy session is available, the task moves to `RETRY_SCHEDULED` without making an X request.
- Task results include safe session provenance: session ID and network context.
- Added tests for session lease release and unavailable-session retry scheduling.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Add raw evidence reprocessing from stored evidence.

## 2026-08-10 - Checkpoint 34: Raw Evidence Reprocessing

Implemented:

- Added a reprocessing service that loads stored raw evidence from completed task results.
- Reprocessing parses existing raw JSON and appends canonical engagement observations without making a new X request.
- Added protected `POST /api/tasks/{task_id}/reprocess`.
- Added safe response serialization with parsed tweet count and canonical counts.
- Documented reprocessing in README and deployment runbook.
- Added tests for reprocessing completed evidence and rejecting incomplete tasks.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Add protocol/parser versioned reprocessing batches for bulk evidence repair.

## 2026-08-10 - Checkpoint 35: Session Health Transitions

Implemented:

- Added durable session health updates.
- Worker maps session-scoped protocol errors to session health transitions.
- Auth/session rejection marks the leased session `AUTH_EXPIRED`.
- Rate limiting marks the leased session `DEGRADED`.
- Unhealthy sessions are excluded from future acquisition leases.
- Added tests for health updates, auth-expired transition, and rate-limit degradation.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Add protocol telemetry persistence.

## 2026-08-10 - Checkpoint 36: Protocol Telemetry

Implemented:

- Added append-only `protocol_attempts` telemetry storage.
- Added migration `002_protocol_telemetry.sql`.
- Worker records success and failure attempts with release, recipe, capability, session, error class, tweet count, cursor presence, and duration.
- Added `GET /api/telemetry` and included telemetry summary in `/api/metrics`.
- Documented telemetry endpoint and storage behavior.
- Added tests for telemetry aggregation and worker success/failure recording.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Add queue backpressure limits.

## 2026-08-10 - Checkpoint 37: Queue Backpressure

Implemented:

- Added `XINGESTION_MAX_ACTIVE_TASKS_PER_CAPABILITY`, defaulting to 100.
- Added active task counting across `CREATED`, `ENQUEUED`, `RUNNING`, and `RETRY_SCHEDULED`.
- Capability submissions now return HTTP `429` before task creation when the per-capability active limit is reached.
- Included the active task limit in storage and metrics responses.
- Documented backpressure behavior.
- Added tests for active counting and rejected submissions.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Add bulk reprocessing jobs.

## 2026-08-10 - Checkpoint 38: Bulk Reprocessing Jobs

Implemented:

- Added durable `reprocess_jobs` with matched, processed, failed, and error counts.
- Added migration `003_reprocess_jobs.sql`.
- Added release-scoped bulk reprocessing for completed tasks with stored raw evidence.
- Added protected `POST /api/reprocess/jobs`.
- Documented bulk reprocessing endpoint.
- Added tests for migration coverage and successful release-scoped bulk reprocessing.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Add asynchronous job execution for large reprocessing batches.

## 2026-08-10 - Checkpoint 39: Session Cooldowns

Implemented:

- Added durable `cooldown_until` metadata to session artifacts.
- Added migration `004_session_cooldowns.sql`.
- Worker now stores a per-session cooldown on HTTP 429 protocol errors using `Retry-After` when available.
- Session acquisition skips cooled-down sessions and allows expired degraded cooldowns back into rotation.
- Successful cooled-down retries restore the session to `HEALTHY`.
- Exposed session cooldowns through `/api/sessions` and cooldown counts through `/api/metrics`.
- Documented cooldown behavior for no-Docker deployment operations.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Add operator session restore and disable paths.

## 2026-08-10 - Checkpoint 40: Session Operator Controls

Implemented:

- Added protected `POST /api/sessions/{session_id}/restore`.
- Added protected `POST /api/sessions/{session_id}/disable`.
- Restore clears cooldown state and marks the session `HEALTHY`.
- Disable marks the session `DISABLED`, keeping metadata but excluding it from worker acquisition.
- Added a Sessions panel to the frontend with restore/disable actions.
- Hardened CI/static tests to require session operator controls.
- Documented session operations in README and the deployment runbook.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Add per-session acquisition attempt counters and last-error visibility.

## 2026-08-10 - Checkpoint 41: Session Attempt Visibility

Implemented:

- Added durable per-session attempt, success, and failure counters.
- Added last attempt time, last success time, last error class, and last error message fields.
- Added migration `005_session_attempt_visibility.sql`.
- Worker now records session attempt start, success, and failure around real protocol acquisition attempts.
- `GET /api/sessions` exposes safe operational attempt metadata.
- Frontend Sessions panel now shows attempt counts and last error details.
- Hardened migration execution for multi-statement additive migrations.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Add protocol drift investigation packages for failed attempts.

## 2026-08-10 - Checkpoint 42: Protocol Drift Investigation Packages

Implemented:

- Added task-scoped protocol telemetry lookup.
- Added `build_protocol_drift_package(...)` for safe JSON investigation bundles.
- Investigation bundles include task error state, release health, recipe revision metadata, session diagnostics, telemetry attempts, raw evidence references, and diagnosis hints.
- Added protected `POST /api/tasks/{task_id}/investigate`.
- Added an Investigate action for dead-letter tasks in the frontend.
- Documented the investigation endpoint in README and deployment runbook.
- Hardened CI/static tests to require the task investigation UI.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Add release quarantine suggestions from repeated drift packages.

## 2026-08-10 - Checkpoint 43: Release Risk Recommendations

Implemented:

- Added release-scoped protocol error signals from telemetry.
- Added advisory release-risk recommendation rules.
- Repeated `OPERATION_NOT_FOUND` failures now recommend release quarantine.
- Repeated parser or unexpected protocol failures recommend investigation.
- Session-scoped rate-limit/auth errors remain session-level signals and do not recommend release quarantine.
- Added `GET /api/releases/current/risk`.
- Included release-risk recommendations in `/api/metrics` and the frontend Metrics panel.
- Documented the advisory behavior in README and deployment runbook.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`

Next:

- Add a one-command deployment preflight that verifies migrations, auth readiness, storage, worker-session availability, and release risk.

## 2026-08-10 - Checkpoint 44: Deployment Preflight Command

Implemented:

- Added `run_preflight.py`.
- Added `DeploymentPreflight` checks for migrations, storage writability, X auth readiness, session availability, release health, advisory release risk, and optional API shape.
- `--base-url` verifies a running deployment exposes the expected JSON API surfaces.
- `--strict-warnings` lets automation fail on warning states.
- Added preflight unit tests without requiring a live server.
- Added preflight to CI compile checks and deployment runbook checks.
- Documented preflight usage in README and the no-Docker deployment runbook.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py`

Next:

- Add an operator-ready packaged health report export for deployments.

## 2026-08-10 - Checkpoint 45: Operator Health Report Export

Implemented:

- Added `run_health_report.py` for no-Docker deployment report export.
- Added `src/xingestion/health_report.py` to package preflight checks, migration state, storage paths, task/outbox counts, canonical counts, telemetry summary, release health, release risk, and safe session diagnostics.
- Reports write to `XINGESTION_DATA_DIR\reports\health-report-*.json` by default, with `--output` support for explicit handoff paths.
- Excluded raw X secrets, credential references, and lease tokens from exported JSON.
- Added unit tests for report persistence, failed preflight reporting, and secret-reference redaction.
- Updated README, deployment runbook, and CI compile/doc checks.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py`
- `python .\run_health_report.py`

Next:

- Add a deployable process supervision guide for running web and worker as durable Windows services or host-managed processes.

## 2026-08-11 - Checkpoint 46: Deployment Process Supervision

Implemented:

- Added `run_supervisor_check.py` for no-Docker supervised deployment verification.
- Added `src/xingestion/supervision.py` to check JSON API liveness, current migrations, storage paths, outbox lag/depth, session availability, release execution state, and optional process-table evidence for web and worker commands.
- Added `docs/process_supervision.md` with Windows Task Scheduler and NSSM setup guidance.
- Documented `run_supervisor_check.py` in README and the deployment runbook.
- Added unit tests for ready deployments, outbox lag failures, checkout-local storage failures, and missing worker process detection.
- Updated CI compile and documentation checks for the new command and guide.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py`
- `python .\run_migrations.py`
- `python .\run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes`

Next:

- Add production log configuration and rotated log guidance for web, worker, and operator commands.

## 2026-08-11 - Checkpoint 47: Production Rotating Logs

Implemented:

- Added `src/xingestion/logging_config.py` with standard-library rotating file logging.
- Added `XINGESTION_LOG_DIR`, `XINGESTION_LOG_LEVEL`, `XINGESTION_LOG_MAX_BYTES`, and `XINGESTION_LOG_BACKUP_COUNT`.
- Initialized logging for web, worker, migrations, preflight, health report, and supervisor check commands.
- Web and worker now print the active log file path at startup and write lifecycle/process events to component logs.
- Added `docs/logging.md` and linked it from README, deployment runbook, and process supervision docs.
- Added unit tests for default log paths, env overrides, and file writes.
- Updated CI documentation checks to require logging guidance.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py`
- `python .\run_migrations.py`
- `python .\run_preflight.py`
- `python .\run_worker.py --once`
- `Get-ChildItem data\logs`

Next:

- Add structured runtime error classification for web/worker logs and health reports.

## 2026-08-11 - Checkpoint 48: Runtime Error Classification

Implemented:

- Added `src/xingestion/errors.py` with structured runtime error envelopes.
- Classified known runtime failures by error class, severity, scope, retryability, and recommended operator action.
- Worker failure paths now persist `error_json.runtime_error` while preserving existing `error_class` and `message` fields.
- Worker failure logs now include structured classification fields.
- Health reports now export `runtime_errors` grouped by class, severity, and scope with recent examples.
- Added unit tests for error classification, worker persistence, and health report runtime error summaries.
- Updated README, deployment runbook, and logging docs.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py`
- `python .\run_health_report.py`
- `python .\run_worker.py --once`
- `Select-String -Path data\reports\health-report-20260811T171943Z.json -Pattern '"runtime_errors"|"by_class"|"operator_action"'`

Next:

- Add an operator-facing failed-task drilldown export command for support handoff.

## 2026-08-11 - Checkpoint 49: Failed Task Support Export

Implemented:

- Added `run_failed_task_export.py` for direct local failed-task support exports.
- Added `src/xingestion/support_export.py` to package task state, runtime error classification, release/session/telemetry context, and raw evidence references.
- Support exports write to `XINGESTION_DATA_DIR\support_exports\failed-task-*.json` by default.
- Reused the existing protocol drift investigation package inside a support-handoff wrapper.
- Excluded raw X secrets, credential references, and raw evidence bodies from exported packages.
- Added tests for export persistence, redaction, classification summary, telemetry inclusion, and non-failed task rejection.
- Updated README, deployment runbook, and CI compile/doc checks.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py`
- Created a synthetic local `DEAD_LETTER` task in ignored `data/tasks.sqlite3` for export verification.
- `python .\run_failed_task_export.py task-4b5d86965dcc4aea841509bab0e3ae93`
- `Select-String -Path data\support_exports\failed-task-task-4b5d86965dcc4aea841509bab0e3ae93-20260811T172515Z.json -Pattern 'FAILED_TASK_SUPPORT_EXPORT|support_summary|runtime_error|operator_action|credential_ref|secret:x|X_AUTH_TOKEN|X_CT0|X_BEARER'`

Next:

- Add operator command to list failed/retryable tasks with recommended actions.

## 2026-08-11 - Checkpoint 50: Operator Task Action List

Implemented:

- Added `run_task_actions.py` to list failed and retryable tasks from local SQLite without requiring the web API.
- Added `src/xingestion/operator_tasks.py` with read-only task action summaries.
- Default listing includes `DEAD_LETTER` and `RETRY_SCHEDULED` tasks.
- Each row includes error class, severity, scope, retryability, replay/cancel/export hints, and a recommended operator action.
- Added `--json`, `--limit`, and `--state` options.
- Added unit tests for failed-task and retry-scheduled action summaries.
- Updated README, deployment runbook, and CI compile/doc checks.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py`
- `python .\run_task_actions.py --limit 5`
- `python .\run_task_actions.py --limit 2 --json`

Next:

- Add frontend task action surfacing for failed/retryable tasks.

## 2026-08-11 - Checkpoint 51: Frontend Task Action Panel

Implemented:

- Added `GET /api/task-actions` backed by the same read-only operator task action summary used by `run_task_actions.py`.
- Added a frontend Needs Attention panel for `DEAD_LETTER` and `RETRY_SCHEDULED` tasks.
- The panel shows task ID, state, severity, attempts, recommended action, and replay/cancel/investigate controls.
- Reused existing protected replay, cancel, and investigate flows from the task ledger.
- Added frontend refreshes after task/session/retention mutations and result polling.
- Added handler-level and static frontend tests.
- Hardened CI static frontend checks for the attention panel and `/api/task-actions`.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py`
- `python .\run_migrations.py`
- Started `python .\run_app.py --host 127.0.0.1 --port 8000`
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/task-actions`
- Served frontend probe confirmed `Needs Attention` is present.

Next:

- Add frontend/export workflow for failed-task support packages.

## 2026-08-11 - Checkpoint 52: Frontend Failed Task Export

Implemented:

- Added protected `POST /api/tasks/{task_id}/export`.
- The route writes the same safe failed-task support package as `run_failed_task_export.py`.
- The Needs Attention panel now shows an Export action for exportable failed/retryable task rows.
- Added frontend rendering for export path, support summary, and redaction metadata.
- Reused the existing admin-token prompt for export writes.
- Added handler-level and static frontend tests.
- Hardened CI static frontend checks for the export button and route call.
- Updated README and deployment runbook.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py`
- `python .\run_migrations.py`
- Started `python .\run_app.py --host 127.0.0.1 --port 8000` with `XINGESTION_ADMIN_TOKEN` set for local verification.
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/task-actions`
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/app.js` confirmed `data-export-task`, `/export`, and `renderSupportExport`.
- `Invoke-WebRequest -UseBasicParsing -Method POST -Headers @{"x-admin-token"="local-test-token"} http://127.0.0.1:8000/api/tasks/task-4b5d86965dcc4aea841509bab0e3ae93/export`
- Confirmed the generated support package exists under `data\support_exports` and contains `FAILED_TASK_SUPPORT_EXPORT`, `support_summary`, and redaction metadata.

Next:

- Add support export retention/listing so operators can see generated support packages.

## 2026-08-11 - Checkpoint 53: Support Export Listing And Retention

Implemented:

- Added support export summaries for `failed-task-*.json` files under `XINGESTION_DATA_DIR\support_exports`.
- Added safe support export retention that deletes only old failed-task export JSON files in that directory.
- Added `GET /api/support-exports` for recent export listing and dry-run cleanup counts.
- Added protected `POST /api/support-exports/retention` for deployment cleanup.
- Added a Support Exports frontend panel with real export rows and cleanup action.
- Added helper, API, and static frontend tests.
- Hardened CI static checks for support export frontend and runbook coverage.
- Updated README and deployment runbook.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py`
- `python .\run_migrations.py`
- Started `python .\run_app.py --host 127.0.0.1 --port 8000` with `XINGESTION_ADMIN_TOKEN` set for local verification.
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/support-exports`
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/app.js` confirmed `/api/support-exports`, `loadSupportExports`, and `runSupportExportRetention`.
- Served frontend probe confirmed `Support Exports` is present.
- `Invoke-WebRequest -UseBasicParsing -Method POST -Headers @{"x-admin-token"="local-test-token"} http://127.0.0.1:8000/api/support-exports/retention`

Next:

- Add an operator download/read endpoint for a selected support export without exposing arbitrary filesystem paths.

## 2026-08-11 - Checkpoint 54: Safe Support Export Detail View

Implemented:

- Added filename-scoped support export reads for `failed-task-*.json` files.
- Added `GET /api/support-exports/{file_name}` without accepting arbitrary filesystem paths.
- Added validation for basename-only export names, file pattern, and safe characters.
- Added a View action in the Support Exports frontend panel.
- Rendered selected support export JSON in the existing diagnostic output area.
- Added helper, API, and static frontend tests for detail reads and unsafe-name rejection.
- Hardened CI static checks for the frontend detail action.
- Updated README and deployment runbook.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py`
- `python .\run_migrations.py`
- Started `python .\run_app.py --host 127.0.0.1 --port 8000` with `XINGESTION_ADMIN_TOKEN` set for local verification.
- `Invoke-RestMethod http://127.0.0.1:8000/api/support-exports` selected a real export filename.
- `Invoke-RestMethod http://127.0.0.1:8000/api/support-exports/<file_name>` returned `FAILED_TASK_SUPPORT_EXPORT` with redaction metadata.
- `Invoke-WebRequest http://127.0.0.1:8000/api/support-exports/..%5Csecrets.json` returned HTTP 400.
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/app.js` confirmed `data-view-support-export`, `renderSupportExportDetail`, and `encodeURIComponent`.
- Served frontend probe confirmed the Support Exports table includes an Action column.

Next:

- Add authenticated support export download with attachment headers for handoff outside the console.

## 2026-08-11 - Checkpoint 55: Authenticated Support Export Download

Implemented:

- Added protected `GET /api/support-exports/{file_name}/download`.
- Download uses the same basename-only `failed-task-*.json` validation as detail reads.
- Returned `Content-Disposition: attachment` with the safe export filename.
- Added a Download action in the Support Exports frontend panel.
- Frontend download uses `fetch` with the existing admin-token prompt and saves the returned blob.
- Added helper, API, and static frontend tests for download behavior.
- Hardened CI static checks for the download action.
- Updated README and deployment runbook.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py`
- `python .\run_migrations.py`
- Started `python .\run_app.py --host 127.0.0.1 --port 8000` with `XINGESTION_ADMIN_TOKEN` set for local verification.
- `Invoke-WebRequest -UseBasicParsing -Headers @{"x-admin-token"="local-test-token"} http://127.0.0.1:8000/api/support-exports/<file_name>/download` returned HTTP 200.
- Download response included `Content-Type: application/json; charset=utf-8`.
- Download response included `Content-Disposition: attachment; filename="<file_name>"`.
- Download body parsed as `FAILED_TASK_SUPPORT_EXPORT`.
- Same download URL without `x-admin-token` returned HTTP 401.
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/app.js` confirmed `data-download-support-export`, `downloadSupportExport`, and `/download`.

Next:

- Add deployment startup checks for writable data, log, report, raw evidence, and support export directories.

## 2026-08-11 - Checkpoint 56: Startup Directory Preflight Checks

Implemented:

- Added preflight startup directory readiness checks for data, raw evidence, reports, support exports, and logs.
- Respected `XINGESTION_LOG_DIR` through the existing logging settings loader.
- Probed each startup directory with real write/delete checks.
- Added unit coverage for the new `startup_directories` check.

Verified:

- `python -m unittest discover -s tests -p test_preflight.py`
- `python -m compileall -q src tests run_preflight.py`

Next:

- Expose startup readiness from the running web app.

## 2026-08-11 - Checkpoint 57: Startup Readiness API

Implemented:

- Added `GET /api/startup`.
- The endpoint returns the same preflight-backed startup and deployment checks without recursively probing the running API.
- Added handler-level API coverage for the endpoint and the `startup_directories` check.

Verified:

- `python -m unittest discover -s tests -p test_northbound_api.py`
- `python -m unittest discover -s tests -p test_preflight.py`
- `python -m compileall -q src tests run_app.py run_preflight.py`

Next:

- Add startup readiness to the frontend.

## 2026-08-11 - Checkpoint 58: Frontend Startup Readiness Panel

Implemented:

- Added a Startup Readiness panel to the web console.
- Loaded real `/api/startup` data and rendered check status/message rows.
- Added static frontend coverage for the panel and loader.

Verified:

- `python -m unittest discover -s tests -p test_frontend_copy.py`
- `python -m compileall -q src tests run_app.py`

Next:

- Add a startup check command for deployment scripts.

## 2026-08-11 - Checkpoint 59: Startup Check Command

Implemented:

- Added `run_startup_check.py`.
- The command loads `.env`, configures logging, runs preflight, prints the startup directory check, and exits nonzero on startup directory failure.

Verified:

- `python .\run_startup_check.py`
- `python -m compileall -q run_startup_check.py src tests`

Next:

- Add startup check to CI and deployment docs.

## 2026-08-11 - Checkpoint 60: Startup Check CI And Docs

Implemented:

- Added `run_startup_check.py` to compile checks.
- Added CI static checks for `/api/startup` frontend usage and runbook startup-check documentation.
- Updated README and deployment runbook command sequences.

Verified:

- `python .\run_startup_check.py`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py`
- `Select-String -Path .github\workflows\ci.yml,README.md,docs\deployment_runbook.md -Pattern "run_startup_check.py|/api/startup"`

Next:

- Include startup readiness in health reports.

## 2026-08-11 - Checkpoint 61: Health Report Startup Readiness

Implemented:

- Added top-level `startup` readiness to health reports.
- Projected the `startup_directories` preflight check into report JSON for fast operator review.
- Added health report tests for the startup section.

Verified:

- `python -m unittest discover -s tests -p test_health_report.py`
- `python -m compileall -q src tests run_health_report.py`
- `python .\run_health_report.py`

Next:

- Use startup readiness in supervisor checks.

## 2026-08-11 - Checkpoint 62: Supervisor Startup Readiness

Implemented:

- Added `/api/startup` to supervisor endpoint checks.
- Added a dedicated `startup` supervision result.
- Supervisor now fails when the running API reports failed startup readiness.
- Added supervisor tests for passing and failed startup readiness.

Verified:

- `python -m unittest discover -s tests -p test_supervision.py`
- `python -m compileall -q src tests run_supervisor_check.py`

Next:

- Add focused failure-case coverage for startup directory probing.

## 2026-08-11 - Checkpoint 63: Startup Directory Failure Coverage

Implemented:

- Added focused failure-case coverage for startup directory probing.
- Simulated a read-only support export directory without relying on platform-specific filesystem permissions.
- Verified preflight reports `startup_directories` as `FAIL` and surfaces the underlying write error.

Verified:

- `python -m unittest discover -s tests -p test_preflight.py`
- `python -m compileall -q src tests run_preflight.py run_startup_check.py`

Next:

- Run final verification and push the ten-step startup readiness stack.

## 2026-08-11 - Checkpoint 64: Startup Readiness Stack Verification

Implemented:

- Ran the final verification pass for the ten-step startup readiness stack.
- Verified unit, compile, startup check, migration, health report, live `/api/startup`, and frontend startup-loader paths.
- Confirmed supervisor now consumes startup readiness from the running API.
- Recorded an existing queue-lag deployment signal from supervisor output instead of masking it.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py`
- `python .\run_startup_check.py`
- `python .\run_migrations.py`
- `python .\run_health_report.py`
- Started `python .\run_app.py --host 127.0.0.1 --port 8000` with `XINGESTION_ADMIN_TOKEN` set for local verification.
- `Invoke-RestMethod http://127.0.0.1:8000/api/startup` returned `ok: true` and `startup_directories: PASS`.
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/app.js` confirmed `/api/startup`, `loadStartup`, and `startupChecks`.
- `python .\run_supervisor_check.py --base-url http://127.0.0.1:8000` confirmed startup readiness but failed on existing queue lag: `oldest_unpublished_lag_seconds=2800 exceeds limit=300`.

Next:

- Add operator queue drain/replay guidance for old unpublished outbox events.

## 2026-08-12 - Checkpoint 65: Outbox Recovery Controls

Implemented:

- Added `SQLiteTaskLedger.list_unpublished_outbox_events(...)` for oldest-first queue visibility.
- Added reusable `xingestion.outbox_operations` helpers for queue summaries and bounded processing.
- Added `run_outbox.py` to inspect unpublished outbox events or process a bounded batch through the live local worker path.
- Added `GET /api/outbox` and admin-gated `POST /api/outbox/process`.
- Added an Outbox Recovery panel to the web console with refresh and bounded process controls.
- Documented no-Docker outbox inspection and recovery in the README and deployment runbook.
- Extended CI smoke checks to require the outbox recovery frontend and deployment docs.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py run_outbox.py`
- `python .\run_outbox.py --json` listed one stale unpublished event for a `DEAD_LETTER` task before processing.
- `python .\run_outbox.py --process --limit 5 --json` processed that event through the local worker path with `Task was already processed or not ready`.
- `python .\run_outbox.py --json` then reported `unpublished_events: 0`.
- Temporary live API smoke on `127.0.0.1:8011` returned `health_ok: true`, `startup_ok: true`, `outbox_pending: 0`, and `processed_events: 0`.
- Temporary live supervisor probe on `127.0.0.1:8012` passed web, migrations, storage, startup, queue, sessions, and release checks; process-table validation was intentionally skipped because this was not a supervised deployment process.

Next:

- Add deeper `SEARCH_TWEETS` parser validation fixtures and drift fingerprints.

## 2026-08-12 - Checkpoint 66: SearchTweets Parser Validation

Implemented:

- Added a checked-in SearchTimeline GraphQL regression fixture for parser-contract validation.
- Added `xingestion.protocol_validation` to parse fixtures and local raw evidence, report tweet counts, engagement coverage, bottom cursor presence, structural fingerprints, and typename fingerprints.
- Added `run_protocol_validation.py` with fixture-only, raw-only, and combined modes.
- Added `GET /api/protocol-validation` and a Protocol Validation panel in the frontend.
- Added saved validation reports under `XINGESTION_DATA_DIR\protocol_validation`.
- Added admin-gated `POST /api/protocol-validation/run` and `GET /api/protocol-validation/reports`.
- Added unit coverage for parser validation reports and the web route.
- Extended CI to compile the validation CLI, run fixture validation, and smoke-check the frontend/runbook surfaces.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py run_outbox.py run_protocol_validation.py`
- `python .\run_protocol_validation.py --fixtures-only --json` passed the checked-in SearchTimeline fixture with 2 parsed tweets, complete engagement metrics, and a bottom cursor.
- `python .\run_protocol_validation.py --raw-only --write --json` passed 10 local raw evidence files with 0 missing engagement warnings and wrote a report to `data\protocol_validation`.
- Temporary live API smoke on `127.0.0.1:8013` returned validation OK, saved a validation report through `POST /api/protocol-validation/run`, and listed saved reports through `GET /api/protocol-validation/reports`.

Next:

- Add a proper secret backend abstraction while keeping `.env` as the local development fallback.

## 2026-08-12 - Checkpoint 67: Secret Provider Abstraction

Implemented:

- Added `XINGESTION_SECRET_PROVIDER` and `XINGESTION_SECRET_DIR` deployment settings.
- Added `xingestion.secrets` with env-backed and file-backed web-session secret providers.
- Kept `env:X_AUTH_TOKEN,X_CT0,X_BEARER` as the local development fallback.
- Added `file:<session-name>` credential references for deployment-mounted JSON secrets outside git.
- Moved web, worker, preflight, and health-report entrypoints onto the config-driven secret provider.
- Added a dedicated preflight `secret_backend` check and safe health-report secret backend status.
- Stopped `/api/sessions` from returning raw credential reference values.
- Added frontend secret-backend status in Metrics.
- Documented env and file provider setup in README and the deployment runbook.
- Extended CI smoke checks for secret provider docs and UI status.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py run_outbox.py run_protocol_validation.py`
- `python .\run_preflight.py` passed migrations, storage, startup directories, secret backend, auth, sessions, and release checks; API probe remained a local-run warning because no base URL was supplied.
- `python .\run_health_report.py` wrote a passing health report.
- Scanned the generated health report and confirmed it did not contain `credential_ref`, `X_AUTH_TOKEN`, `X_CT0`, or `X_BEARER`.
- Temporary live API smoke on `127.0.0.1:8015` reported `secret_provider: env`, `secret_configured: true`, `reference_scheme: env`, and confirmed `/api/sessions` did not contain `credential_ref`.

Next:

- Add more capability scaffolding only after the `SEARCH_TWEETS` vertical slice remains stable under the new secret abstraction.

## 2026-08-12 - Checkpoint 68: Session Registry and Per-Session Auth

Implemented:

- Added `XINGESTION_SESSION_REGISTRY` for deployment-mounted session inventory files.
- Added `xingestion.sessions.registry` for safe JSON session registry loading and import.
- Added `run_sessions.py` to import/list session metadata without printing credential reference values.
- Added startup imports for web and worker when `XINGESTION_SESSION_REGISTRY` is configured.
- Added admin-gated `POST /api/sessions/import` and a frontend Sessions import control.
- Updated the worker to resolve web-session auth from the leased session's own credential reference through the configured secret provider.
- Added failure handling so incomplete per-session auth marks only that session `AUTH_EXPIRED`, releases its lease, and schedules the task for retry without making an X request.
- Documented the registry JSON shape and no-secret import behavior in README and the deployment runbook.
- Extended CI smoke checks for session registry docs and UI import.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py run_outbox.py run_protocol_validation.py run_sessions.py`
- `python .\run_sessions.py --import-registry F:\x-scraper\data\session-cli-check\sessions.json --json` imported one file-backed session and returned only safe reference metadata.
- `python .\run_sessions.py --json` listed imported session metadata without `credential_ref` values.
- Temporary live API smoke on `127.0.0.1:8016` imported one configured registry session through `POST /api/sessions/import`, listed two sessions through `GET /api/sessions`, and confirmed the JSON did not contain `credential_ref`.
- `python .\run_preflight.py` passed migrations, storage, startup directories, secret backend, auth, sessions, and release checks with two available sessions.
- `python .\run_protocol_validation.py --fixtures-only --json` passed the checked-in SearchTimeline parser fixture.

Next:

- Add network allocation policy metadata and worker selection controls when moving beyond the local `network_context` label.

## 2026-08-10 - Checkpoint 30: JSON API Error Hardening

Implemented:

- API misses under `/api/*` now return JSON 404 payloads instead of SimpleHTTP HTML.
- Frontend JSON parsing now reports the exact endpoint, content type, and HTTP status when an API returns HTML or another non-JSON response.
- Initial dashboard loaders now render endpoint errors inline instead of throwing uncaught parser errors.
- Added tests for frontend non-JSON reporting and API JSON error payload shape.

Verified:

- `python -m unittest discover -s tests`
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py`
- Fresh local server probe: `GET /api/retention` returned JSON.
- Fresh local server probe: missing `/api/*` route returned JSON 404.

Next:

- Add multi-page pagination orchestration with bounded cursor tasks.

## 2026-08-12 - Checkpoint 69: Unified Source Package Layout

Implemented:

- Moved the visible protocol runtime package from `src/xrev/` into `src/xingestion/xprotocol/`.
- Updated production code, CLI entrypoints, and tests to import protocol runtime code through `xingestion.xprotocol`.
- Kept the protocol/runtime boundary intact as an internal subsystem instead of a separate sibling source tree.
- Updated the frontend console label from the older subsystem name to `X Scraper live console`.
- Updated README/current-stage documentation to describe one product package with an internal protocol module.
- Restored `FINAL_PRODUCT_SPEC.md` unchanged so the canonical spec remains the source reference.

Verified:

- `python -m unittest discover -s tests` passed 130 tests.
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py run_outbox.py run_protocol_validation.py run_sessions.py`
- `python .\run_preflight.py` passed migrations, storage, startup directories, secret backend, auth, sessions, and release checks; API probe remained a local-run warning because no base URL was supplied.
- `python .\run_protocol_validation.py --fixtures-only --json` passed the checked-in SearchTimeline parser fixture with two tweets and complete engagement metrics.
- `python .\run_startup_check.py` passed startup directory checks.
- Temporary live server on `127.0.0.1:8018` returned JSON health/storage/startup OK and served `/` plus `/app.js`; the frontend contained `X Scraper live console`.

Next:

- Continue with network allocation policy metadata and worker selection controls when moving beyond the local `network_context` label.

## 2026-08-12 - Checkpoint 70: Network Policy Session Routing

Implemented:

- Added validated session network policies parsed from `network_context` values shaped as `kind[:route][:region]`.
- Supported `direct`, `proxy`, and `vpn` network kinds with public-safe `network_policy` metadata.
- Added `XINGESTION_WORKER_NETWORK_CONTEXT` so deployed workers can lease only sessions matching a specific route or pool.
- Updated `SessionStore.acquire_session(...)` to filter healthy/cooled-down sessions by worker network requirement.
- Stored selected session network policy in task results and selected network context in protocol telemetry attempts.
- Added migration `006_protocol_attempt_network.sql` for durable telemetry route attribution.
- Exposed parsed network policy through `GET /api/sessions`, `run_sessions.py --json`, health reports, and investigation/support packages.
- Added a Network column to the Sessions frontend panel.
- Updated README, deployment runbook, and current-stage documentation for no-Docker deployment usage.

Verified:

- `python -m unittest discover -s tests` passed 135 tests.
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py run_outbox.py run_protocol_validation.py run_sessions.py`
- `python .\run_migrations.py` applied migration `006` to `F:\x-scraper\data\tasks.sqlite3`.
- `python .\run_preflight.py` passed migrations, storage, startup directories, secret backend, auth, sessions, and release checks; API probe remained a local-run warning because no base URL was supplied.
- `python .\run_startup_check.py` passed startup directory checks.
- `python .\run_health_report.py` wrote a passing report.
- `python .\run_sessions.py --json` returned two sessions with parsed `network_policy` metadata and no credential reference values.
- `python .\run_protocol_validation.py --fixtures-only --json` passed the checked-in SearchTimeline parser fixture.
- Temporary live server on `127.0.0.1:8019` returned sessions with parsed network policy, telemetry JSON, `/`, and `/app.js`; the frontend contained the Network column and `formatNetworkPolicy`.

Next:

- Add worker-level route health statistics and route-aware supervisor thresholds before adding managed proxy/VPN provisioning.

## 2026-08-12 - Checkpoint 71: Route Health Statistics

Implemented:

- Added route-level telemetry summaries grouped by `network_context`.
- Added `GET /api/network-health` with safe success/failure counts, failure rate, distinct session count, latest attempt timestamps, and route-specific error classes.
- Included network route health in no-Docker health reports.
- Added route-aware supervisor checks with configurable `--required-network-context`, `--max-network-failure-rate`, and `--min-network-attempts`.
- Added a Network Health panel to the existing frontend console.
- Updated README, deployment runbook, and process supervision docs for the new deployment checks.

Verified:

- `python -m unittest discover -s tests -p "test_telemetry_store.py"` passed 2 tests.
- `python -m unittest discover -s tests -p "test_northbound_api.py"` passed 21 tests.
- `python -m unittest discover -s tests -p "test_health_report.py"` passed 2 tests.
- `python -m unittest discover -s tests -p "test_supervision.py"` passed 8 tests.
- `python -m unittest discover -s tests -p "test_frontend_copy.py"` passed 3 tests.
- `python -m unittest discover -s tests` passed 140 tests.
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py run_outbox.py run_protocol_validation.py run_sessions.py`
- `python .\run_preflight.py` passed migrations, storage, startup directories, secret backend, auth, sessions, and release checks; API probe remained a local-run warning because no base URL was supplied.
- `python .\run_startup_check.py` passed startup directory checks.
- `python .\run_health_report.py` wrote a passing report.
- `python .\run_protocol_validation.py --fixtures-only --json` passed the checked-in SearchTimeline parser fixture.
- Temporary live server on `127.0.0.1:8021` returned JSON from `/api/network-health`, served `/` and `/app.js` with the Network Health UI, and passed `run_supervisor_check.py --base-url http://127.0.0.1:8021 --required-network-context direct --min-network-attempts 1` with the expected first-run network warning.

Next:

- Add route-aware release-risk recommendations and operator-facing remediation guidance before managed proxy/VPN provisioning.

## 2026-08-12 - Checkpoint 72: Route Remediation Recommendations

Implemented:

- Added active-release network route remediation recommendations for repeatedly failing concrete `network_context` routes.
- Kept route remediation separate from release quarantine by returning `NETWORK_REMEDIATION_RECOMMENDED` instead of protocol-release quarantine for route-specific failures.
- Added route `operator_action` guidance for rate limits, auth rejection, network errors, missing healthy sessions, and unknown route failures.
- Scoped `/api/network-health` and health-report route summaries to the active protocol release.
- Added route recommendations to `/api/network-health`, health reports, `/api/releases/current/risk`, and the frontend Network Health panel.
- Extended preflight live API shape checks to require `/api/network-health`.
- Updated README, deployment runbook, and current-stage documentation.

Verified:

- `python -m unittest discover -s tests -p "test_investigation.py"` passed 6 tests.
- `python -m unittest discover -s tests -p "test_telemetry_store.py"` passed 3 tests.
- `python -m unittest discover -s tests -p "test_northbound_api.py"` passed 21 tests.
- `python -m unittest discover -s tests -p "test_health_report.py"` passed 2 tests.
- `python -m unittest discover -s tests -p "test_preflight.py"` passed 5 tests.
- `python -m unittest discover -s tests -p "test_frontend_copy.py"` passed 3 tests.
- `python -m unittest discover -s tests` passed 143 tests.
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py run_outbox.py run_protocol_validation.py run_sessions.py`
- `python .\run_preflight.py` passed migrations, storage, startup directories, secret backend, auth, sessions, and release checks; API probe remained a local-run warning because no base URL was supplied.
- `python .\run_startup_check.py` passed startup directory checks.
- `python .\run_health_report.py` wrote a passing report.
- `python .\run_protocol_validation.py --fixtures-only --json` passed the checked-in SearchTimeline parser fixture.
- Temporary live server on `127.0.0.1:8022` returned active-release `/api/network-health` JSON, active-release risk JSON with `operator_action`, served `/` and `/app.js` with the Network Health action column, passed `run_preflight.py --base-url http://127.0.0.1:8022`, and passed supervisor with the expected first-run route warning.

Next:

- Add a no-Docker route remediation audit/export command so operators can snapshot failing route evidence before rotating sessions or network paths.

## 2026-08-12 - Checkpoint 75: Tokenless Trusted Console Controls

Implemented:

- Removed the admin-token requirement from trusted-console operator routes.
- Removed frontend admin-token prompting and `x-admin-token` header injection from operator actions, downloads, retention, outbox processing, session controls, and protocol validation saves.
- Removed `XINGESTION_ADMIN_TOKEN` from current environment examples and deployment guidance.
- Removed admin-token state from active app configuration, smoke checks, storage metrics, and health-report config output.
- Updated tests to assert operator routes work without configured or supplied admin-token headers.

Verified:

- `rg` found no active `Admin token`, `adminHeaders`, `x-admin-token`, `XINGESTION_ADMIN_TOKEN`, `admin_token_configured`, or `admin_token` references in `src`, tests, README, deployment runbook, or `.env.example`.
- `node --check src\xingestion\web\static\app.js`
- `python -m unittest discover -s tests -p "test_config.py"` passed 2 tests.
- `python -m unittest discover -s tests -p "test_northbound_api.py"` passed 21 tests.
- `python -m unittest discover -s tests -p "test_smoke.py"` passed 2 tests.
- Restarted the live server on `127.0.0.1:8023`.
- Live `POST /api/tasks/{task_id}/investigate` succeeded without an admin-token header.
- Live `POST /api/protocol-validation/run` accepted the request without an admin-token header and wrote a report.
- Live `/app.js` contains no prompt, admin-header helper, admin-token text, or `x-admin-token` header usage.

Next:

- Add deployment-boundary auth separately if this trusted console is exposed beyond a private operator network.

## 2026-08-12 - Checkpoint 76: Immediate Worker Dispatch for Console Tasks

Implemented:

- Fixed replay and live acquisition tasks getting stuck in `CREATED` when no separate/manual outbox processing was triggered.
- Added server-side bounded outbox draining after capability task creation and replay when the live app has an attached local worker.
- Kept the explicit `/api/outbox/process` endpoint for manual recovery and background-style operation.
- Added regression coverage proving task submission and replay process through an attached worker immediately.

Verified:

- `python -m unittest discover -s tests -p "test_northbound_api.py"` passed 23 tests.
- `python -m unittest discover -s tests -p "test_outbox_operations.py"` passed 2 tests.
- `python -m unittest discover -s tests -p "test_frontend_copy.py"` passed 3 tests.
- Restarted the live server on `127.0.0.1:8023`.
- Live `POST /api/search-tweets` created task `task-669d2ea02dfc4bf18fa962474244763e`, auto-processed 1 outbox event, reached `DONE`, returned result HTTP 200, and left 0 unpublished outbox events.
- Live `POST /api/tasks/task-4b5d86965dcc4aea841509bab0e3ae93/replay` created replay task `task-36cc21c99e5f474491f9b6543e458784`, auto-processed 1 outbox event, reached `DONE`, returned result HTTP 200, and left 0 unpublished outbox events.

Next:

- Surface the auto-dispatch status in the frontend summary so operators can see whether work was processed immediately or left for a background worker.

## 2026-08-12 - Checkpoint 74: Frontend Fitment Correction

Implemented:

- Removed cramped two-column operational bands that forced wide tables into half-width panels.
- Removed sticky table headers inside nested scroll containers to prevent visual stacking and overlap.
- Kept dense task acquisition controls and task ledger side-by-side only on wide screens.
- Made heavy operational tables full-width on desktop and horizontally scrollable only inside their panel on small screens.
- Added a mobile-specific task ledger layout so retry/replay/investigate controls wrap inside the panel instead of clipping.

Verified:

- `node --check src\xingestion\web\static\app.js`
- `python -m unittest discover -s tests -p test_frontend_copy.py` passed 3 tests.
- `python -m unittest discover -s tests` passed 146 tests.
- Live CSS from `http://127.0.0.1:8023/styles.css` includes the corrected mobile command-rail and workspace table rules.
- Chrome headless loaded desktop and mobile captures before the last mobile-only retry, confirming the main layout no longer overlaps; final served CSS was checked directly after the mobile task-ledger correction.

Next:

- Add a no-Docker route remediation audit/export command so operators can snapshot failing route evidence before rotating sessions or network paths.

## 2026-08-12 - Checkpoint 73: Frontend Control Room Organization

Implemented:

- Reorganized the static frontend into a production operator console with a command rail, live evidence area, metrics strip, readiness panels, operator queue, session/network panels, and lifecycle/export controls.
- Kept the console no-Docker and static-file deployable while preserving the existing endpoint bindings and DOM ids used by the live API wiring.
- Added responsive layout rules for desktop, tablet, and mobile views with scroll-safe tables and stable controls.
- Added frontend HTML escaping for live API fields including tweet content, user fields, session errors, export names, paths, route recommendations, and fallback error rows.
- Preserved the no-mock frontend contract and the existing live acquisition workflow.

Verified:

- `node --check src\xingestion\web\static\app.js`
- `python -m unittest discover -s tests -p test_frontend_copy.py` passed 3 tests.
- `python -m unittest discover -s tests` passed 146 tests.
- `python -m compileall -q src tests run_app.py run_worker.py run_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py run_outbox.py run_protocol_validation.py run_sessions.py`
- Live server on `127.0.0.1:8023` served the reorganized shell, the new `console-shell` CSS, and the escaped frontend JavaScript.
- Live API probes returned JSON 200 from `/api/health`, `/api/metrics`, `/api/network-health`, and `/api/tasks`.

Next:

- Add a no-Docker route remediation audit/export command so operators can snapshot failing route evidence before rotating sessions or network paths.

## 2026-08-12 - Checkpoint 77: Approved Release Resolution and Capture Replay Validation

Implemented:

- Added a durable `approved_protocol_release` pointer and migration `007_approved_protocol_release.sql` so workers resolve an approved release ID before loading a manifest.
- Changed web, worker, preflight, health report, and protocol validation entrypoints to load the exact manifest matching the approved release ID.
- Added a worker guard that rejects tasks planned for a different release instead of executing them under the active approved release.
- Added replayable request metadata to raw SearchTweets browser captures.
- Added a direct-replay validator that replays recent replayable browser captures through the approved release recipe, stores linked `direct_replay` raw evidence, and compares parser counts plus structural/typename fingerprints.
- Documented approved-release resolution and capture/replay validation in README, the deployment runbook, and the current-stage report.

Verified:

- `python -m unittest discover -s tests -p "test_release_store.py"` passed 5 tests.
- `python -m unittest discover -s tests -p "test_protocol_validation.py"` passed 6 tests.
- `python -m unittest discover -s tests -p "test_one_attempt_acquisition.py"` passed 3 tests.
- `python -m unittest discover -s tests -p "test_local_worker.py"` passed 22 tests.

Next:

- Add an explicit operator command/API for approving a newly staged release when more than one manifest exists.
