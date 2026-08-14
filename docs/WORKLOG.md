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

## 2026-08-12 - Checkpoint 78: Operator Release Approval Controls

Implemented:

- Added release inventory objects that combine staged manifests, approved-release pointer state, release health, capability bindings, and recipe revisions.
- Added `run_releases.py` for no-Docker release listing, current approved release inspection, and explicit release approval.
- Added `GET /api/releases` and `POST /api/releases/approve` to the trusted console API.
- Reloaded the live planner and local worker after approval so future tasks bind to the exact newly approved manifest without a server restart.
- Added a frontend Protocol Governance panel for release inventory and approval actions.
- Documented the release approval flow in README, the deployment runbook, and the current-stage report.

Verified:

- `python -m unittest discover -s tests -p "test_release_store.py"` passed 6 tests.
- `python -m unittest discover -s tests -p "test_northbound_api.py"` passed 25 tests.
- `python -m unittest discover -s tests -p "test_frontend_copy.py"` passed 3 tests.
- `node --check src\xingestion\web\static\app.js` passed.

Next:

- Add promotion safety checks that require passing fixture/raw/capture-replay validation before approving a staged release.

## 2026-08-12 - Checkpoint 79: Promotion Safety Gates

Implemented:

- Added reusable promotion safety reports for staged protocol releases.
- Safety checks cover manifest presence, manifest release ID match, release health, binding presence, checked-in fixture parser validation, and browser-capture/direct-replay comparison when pairs exist.
- Added `run_releases.py check ... --json`.
- Normal `run_releases.py approve ...` now blocks failed promotion safety unless `--force` is explicitly supplied.
- `POST /api/releases/approve` now returns HTTP `409` with the failed safety report unless `force: true` is explicitly supplied.
- Release inventory API and frontend Protocol Governance panel now surface safety pass/blocked state.

Verified:

- Focused promotion, release-store, API, and frontend tests pass.

Next:

- Persist promotion reports as audit artifacts before approval/force approval.

## 2026-08-12 - Checkpoint 80: Promotion Audit Artifacts

Implemented:

- Added redacted `RELEASE_PROMOTION_AUDIT` packages for release safety checks, blocked approvals, normal approvals, and forced approvals.
- Promotion audits write to `XINGESTION_DATA_DIR\release_promotions\promotion-*.json` by default.
- Added safe audit listing/detail helpers that reject arbitrary paths and unreadable JSON.
- Extended `run_releases.py` with audit writing for `check` and `approve`, plus `audits` and `audit <name>` commands.
- Added `GET /api/releases/audits` and `GET /api/releases/audits/{name}` to the trusted console API.
- Added a frontend Promotion Trail panel with audit history and JSON detail viewing.
- Documented promotion audit storage and read paths in the deployment runbook and current-stage report.

Verified:

- `python -m compileall -q src tests run_releases.py` passed.
- `python -m unittest discover -s tests -p "test_release_promotion.py"` passed 3 tests.
- `python -m unittest discover -s tests -p "test_northbound_api.py"` passed 28 tests.
- `python -m unittest discover -s tests -p "test_frontend_copy.py"` passed 3 tests.
- `node --check src\xingestion\web\static\app.js` passed.
- `python -m unittest discover -s tests` passed 164 tests.
- `python .\run_releases.py check xrev-search-tweets-2026-08-10-candidate-1 --json` wrote a promotion audit under `data\release_promotions`.
- `python .\run_releases.py audits --limit 5 --json` listed the generated promotion audit.
- `python .\run_releases.py audit promotion-xrev-search-tweets-2026-08-10-candidate-1-check-20260812T072318Z.json --json` read the generated audit detail.
- Live `GET /api/health`, `GET /api/releases`, `GET /api/releases/audits`, and `GET /api/releases/audits/{name}` passed on `http://127.0.0.1:8023`.

Next:

- Add retention and export/download controls for promotion audit artifacts if audit volume grows.

## 2026-08-12 - Checkpoint 81: Promotion Audit Lifecycle Controls

Implemented:

- Added promotion audit retention that deletes only old `promotion-*.json` files under `XINGESTION_DATA_DIR\release_promotions`.
- Added a conservative `run_releases.py prune-audits` command that dry-runs by default and requires `--apply` to delete.
- Added protected `POST /api/releases/audits/retention` for live cleanup using `XINGESTION_RETENTION_DAYS`.
- Added safe `GET /api/releases/audits/{name}/download` responses with attachment headers.
- Extended the Promotion Trail frontend with dry-run cleanup counts, Clean old, View, and Download controls.
- Added CI/frontend/docs assertions for promotion audit lifecycle visibility.

Verified:

- `python -m compileall -q src tests run_releases.py` passed.
- `python -m unittest discover -s tests -p "test_release_promotion.py"` passed 4 tests.
- `python -m unittest discover -s tests -p "test_northbound_api.py"` passed 28 tests.
- `python -m unittest discover -s tests -p "test_frontend_copy.py"` passed 3 tests.
- `node --check src\xingestion\web\static\app.js` passed.
- `python -m unittest discover -s tests` passed 165 tests.
- `python .\run_releases.py prune-audits --json` dry-ran promotion audit cleanup with `deleted_audits=0`.
- `python .\run_releases.py audits --limit 5 --json` listed the existing promotion audit.
- Live `GET /api/health`, `GET /api/releases/audits`, `GET /api/releases/audits/{name}/download`, and `POST /api/releases/audits/retention` passed on `http://127.0.0.1:8023`.

Next:

- Add scheduled/operator reporting for promotion audit volume if deployment volume grows.

## 2026-08-12 - Checkpoint 82: Task Ledger and Outbox on PostgreSQL + Redis Streams

Implemented:

- Added `PostgresTaskLedger`, a full port of `SQLiteTaskLedger`'s fenced-write behavior (lease token + delivery generation + state guards) onto PostgreSQL, using `RETURNING`-based writes and `FOR UPDATE SKIP LOCKED` claims. Widened the `TaskLedger` Protocol to the full method surface shared by both backends.
- Added `docker-compose.yml` for local Postgres (port `55432`, avoiding a conflict with an existing native Postgres service on this machine) and Redis; the application processes (web, worker, dispatcher) stay uncontainerized.
- Added a hand-rolled `PostgresMigrationRunner` (`psycopg`, no ORM/Alembic) and `run_postgres_migrations.py`.
- Added `RedisOutboxDispatcher`: claims unpublished outbox rows, `XADD`s to a Redis stream, then marks published -- so a crash between the two produces a harmless duplicate delivery rather than a lost one.
- Redesigned `LocalWorker.process_one()` around `XREADGROUP`/`XACK` with `XAUTOCLAIM`-based reclaim of stale deliveries (worker crash recovery), fenced through the same Postgres lease-acquisition check used before.
- Swapped every remaining call site (`live_server.py`, `health_report.py`, `reprocessing.py`, `operator_tasks.py`, `support_export.py`, `investigation.py`, `preflight.py`, `run_outbox.py`, `run_task_actions.py`) off `SQLiteTaskLedger`, closing three raw-SQL bypasses in the process (`list_recent_task_errors`, `list_done_task_ids_for_release`, `list_recent_tasks`). `preflight.py` gained Postgres/Redis reachability checks; `run_supervisor_check.py` now expects `run_dispatcher.py` in the process table alongside web/worker.
- Retired `SQLiteTaskLedger` entirely; `ledger.py` now holds only the shared `TaskLedger` Protocol and dataclasses.
- Fixed a real bug found during end-to-end verification: `PostgresTaskLedger` and `PostgresMigrationRunner` sharing one `ConnectionPool` caused a `KeyError`, since `psycopg_pool` does not reset `row_factory` between checkouts and the migration runner assumed the default tuple factory. Added a regression test that forces connection reuse to make the failure mode deterministic.
- Added a Postgres/Redis-backed CI job on Ubuntu (service containers, Python 3.11/3.12) alongside the existing Windows matrix; updated the deployment runbook, `CURRENT_STAGE.md`, and `process_supervision.md` to match.
- Sessions, canonical tweet/engagement data, releases, protocol telemetry, and reprocess jobs stay on SQLite -- this migration is scoped to the task ledger, outbox, and dispatch layer only.

Verified:

- `python -m compileall -q src tests run_*.py` passed.
- `python -m unittest discover -s tests` passed 171 tests, including 17 `PostgresTaskLedger` contract tests, 23 consumer-group worker tests (including a simulated crash/`XAUTOCLAIM` reclaim scenario), and 2 migration-runner tests (including the shared-pool regression test).
- Live end-to-end run: `docker compose up -d`, `run_postgres_migrations.py` + `run_migrations.py`, then `run_app.py` + `run_worker.py` + `run_dispatcher.py` as real processes. Submitted a `SEARCH_TWEETS` task through the actual frontend; it flowed Postgres to dispatcher to Redis Streams to consumer-group worker to a real X API call to 24 parsed tweets to `DONE`, rendered live in the UI.
- `run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes` passed all 9 checks against the running three-process stack.

Next:

- Consider `LISTEN`/`NOTIFY` for lower-latency outbox dispatch if the 1s poll interval becomes a bottleneck.
- Add Redis consumer-group lag/pending-entry-count metrics to `run_supervisor_check.py`/health reporting (currently only Postgres outbox lag is surfaced).
- Load/chaos-test the crash-recovery path before treating it as production-certified; move toward managed/clustered Postgres and Redis when genuine production deployment is the next priority.

## 2026-08-13 - Checkpoint 83: Redis Consumer-Group Lag and Pending-Entry Metrics

Implemented:

- Added `redis_queue_stats()` (`src/xingestion/dispatch/redis_stream_stats.py`), a small helper around `XLEN`/`XINFO GROUPS`/`XPENDING`/`XPENDING` range that reports stream length, whether the consumer group exists, pending-entry count, Redis-computed group lag, and the oldest pending entry's idle time.
- Wired it into `/api/metrics` (`live_server.py`, new `redis_queue` key) and `build_health_report()` (`health_report.py`, new `redis_queue` section, opening its own short-lived Redis connection alongside the existing Postgres-only `_task_dict`).
- Added a `redis_queue` supervision check to `DeploymentSupervisorCheck` (`supervision.py`): FAILs on stats-collection errors, WARNs when the consumer group has not been created yet, FAILs when pending-entry count or oldest-pending idle time exceed new `--max-redis-pending-entries`/`--max-redis-pending-idle-seconds` flags on `run_supervisor_check.py` (defaults 100 / 300s, mirroring the existing outbox-lag check).

Verified:

- `python -m compileall -q src tests run_supervisor_check.py` passed.
- `python -m unittest discover -s tests` passed 178 tests, including 3 new `redis_queue_stats` unit tests (group missing, lag with no pending entries, pending count/idle time after an unacked read) and 4 new supervision tests (backlogged pending entries, stale pending entry, missing consumer group as WARN not FAIL, unavailable stats as FAIL).
- `python run_health_report.py` against the live local stack (`docker compose` Postgres/Redis already running) wrote a report with a populated `redis_queue` section (`group_exists=true`, `stream_length=33`, `pending_count=0`, `lag=0`).
- `run_supervisor_check.py --base-url http://127.0.0.1:8000` against an already-running `run_app.py` process showed `redis_queue` as `WARN` with `group=None` -- confirmed via `curl /api/metrics` that this is the pre-existing process still serving old code without the new key, not a bug; a restart of the running stack picks up the change.

Next:

- Restart the local `run_app.py`/`run_worker.py`/`run_dispatcher.py` stack to pick up the new `/api/metrics` `redis_queue` key.
- Load/chaos-test the crash-recovery path before treating it as production-certified; move toward managed/clustered Postgres and Redis when genuine production deployment is the next priority.

## 2026-08-13 - Checkpoint 84: Delivery Load, Soak, and Crash-Recovery Test Suite

Implemented:

- Added `tests/test_delivery_load.py`, an opt-in test suite (`XINGESTION_RUN_LOAD_TESTS=1`; skipped by default so the regular suite stays fast) covering three gaps the existing single-task `test_local_worker.py` tests didn't reach:
  - `test_many_tasks_drain_with_no_loss_or_stuck_deliveries`: dispatches 150 outbox events, drains them with 4 concurrent `LocalWorker`s round-robin, asserts every task reaches `DONE` exactly once and the Redis consumer group ends at `pending_count=0`/`lag=0`.
  - `test_crash_recovery_reclaims_many_stale_deliveries_under_load`: 3 consumers each read a share of 30 messages via `_read_next_delivery()` and never ack (simulated crash, held apart by the default 300s `redis_claim_min_idle_ms` so they don't reclaim each other), then 2 recovering workers with `redis_claim_min_idle_ms=0` drain all 30 via `XAUTOCLAIM` -- exercises multiple simultaneously-stale consumers, which the existing single-crash test doesn't.
  - `test_soak_repeated_dispatch_process_cycles_leave_no_backlog`: 20 create/dispatch/process cycles, asserting zero unpublished outbox events and zero Redis pending entries after every cycle, to catch a slow per-cycle leak that a single run wouldn't show.
- Added the new file to the Postgres/Redis CI job (`.github/workflows/ci.yml`) with `XINGESTION_RUN_LOAD_TESTS: "1"` set for that job only.

Verified:

- `python -m compileall -q src tests run_*.py` passed.
- Discovered during first live run: this repo's Postgres-backed tests have no per-test database isolation from whatever else is pointed at the same local Postgres DSN. Several stacked-up `run_dispatcher.py`/`run_worker.py` processes (leftover from repeated local launches) were racing the new tests for the same `outbox_events` rows, which surfaced as short counts (139/150, 26/30) on the first attempt -- not a bug in the tests or the app, just local-environment contention that CI's fresh single-purpose Postgres container doesn't have. Stopped the stray local dispatcher/worker processes (user-approved) and re-ran clean.
- `XINGESTION_RUN_LOAD_TESTS=1 python -m unittest discover -s tests -p "test_delivery_load.py" -v` passed all 3 tests in ~23s against an idle local stack.
- `python -m unittest discover -s tests` passed 181 tests (178 + 3, the 3 new tests correctly `skipped` without the env var set).

Next:

- Look at why multiple duplicate `run_app.py`/`run_dispatcher.py`/`run_worker.py` processes had accumulated locally -- likely `run_all.ps1` not cleaning up a prior run before starting a new one.
- Real OS-level process-kill chaos testing and a sustained multi-hour soak at production scale remain open before calling the delivery path production-certified.
- Restart the local `run_app.py`/`run_worker.py`/`run_dispatcher.py` stack (stopped during this checkpoint's verification) to pick up the `redis_queue` metrics key from Checkpoint 83.

## 2026-08-13 - Checkpoint 85: Persisted Recipe-Level Release Validation Records

Implemented:

- Added `RecipeValidationStore` (`src/xingestion/releases/validation_records.py`), a small SQLite-backed store (new `recipe_validation_record` table, migration `008_recipe_validation_record.sql`) that persists first-class validation records keyed by `release_id`/`recipe_revision_id`/`composition_hash`/`runtime_version`/`validation_type`/`ok`/`summary` -- a queryable history alongside the existing JSON report artifacts in `data/protocol_validation/`, not a replacement for them.
- Added `record_recipe_validation_results()`, which writes one record per (approved-manifest capability binding recipe x validation type), so a manifest with multiple bindings gets validation history for each recipe composition it actually runs.
- Added `xingestion.__version__` (`"0.1.0"`, matching `pyproject.toml`) as the `runtime_version` default -- no such constant existed anywhere in the codebase before this.
- Wired persistence into both places recipe validation already runs: `build_promotion_safety_report()` (`releases/promotion.py`, every `run_releases.py check`/`approve` and `POST /api/releases/approve`) and the operator-triggered `POST /api/protocol-validation/run` (`live_server.py`), covering both fixture/raw-evidence validation and browser-capture/direct-replay comparison results.
- Added `GET /api/releases/validation-records` returning the current release's recent record history.

Verified:

- `python -m compileall -q src tests run_*.py` passed.
- `python -m unittest discover -s tests` passed 187 tests (179 non-skipped + the 3 opt-in load tests skipped + 5 new `RecipeValidationStore` unit tests), including updated `test_release_promotion.py` (asserts `build_promotion_safety_report` persists 2 records with the correct release/recipe/composition-hash identity) and `test_northbound_api.py` (asserts the validation-run route persists and returns records, and the new list route reads them back). `tests/test_migrations.py`'s `EXPECTED_MIGRATIONS` tuple updated for the new `008` migration.

Next:

- Consider surfacing validation-record history in the frontend Protocol Governance panel (deferred this checkpoint to keep scope to persistence + API).
- Decide whether `run_protocol_validation.py`'s CLI path should also persist records (currently only the two live/promotion call sites do).

## 2026-08-13 - Checkpoint 86: Fixed run_all.ps1 Orphaned-Process Leak

Implemented:

- Root-caused the duplicate `run_app.py`/`run_dispatcher.py`/`run_worker.py` processes found accumulated locally during Checkpoint 84: `Start-ManagedProcess` launched each service through a nested `powershell -Command "Set-Location ...; python .\script.py"` wrapper and recorded *the wrapper's* PID in `pids.json`. `Stop-Process` on that PID does not kill its child on Windows, so every `-Stop`/`-Restart` left the real `python.exe` running, orphaned and untracked, while the PID file was deleted -- the next run had nothing to detect as "already running" and happily started another full set on top.
- Fixed `Start-ManagedProcess` to launch `python.exe` directly via `Start-Process -FilePath "python" -WorkingDirectory $Root` (env `PYTHONPATH=src` set in the launching process and inherited), so the PID recorded in `pids.json` is now the actual worker process, not an intermediary shell.
- Added `Stop-StrayManagedProcesses`, a command-line-matching sweep (by script name only, not by `$Root` substring -- the very orphans it exists to catch were launched with a relative `.\script.py` path via `Set-Location`, so their `CommandLine` never contains the repo's absolute path) that runs at the end of `Stop-ManagedProcesses` and defensively before starting a fresh set when nothing is tracked as live, to clean up both pre-fix orphans and any future leak.
- Removed the now-dead `Quote-Single` helper (no longer needed once commands are passed as argument arrays instead of an interpolated shell string).

Verified:

- `[scriptblock]::Create((Get-Content -Raw .\run_all.ps1))` parses cleanly (same check CI runs).
- Live: found 4 real orphaned `run_app.py` processes left over from before this fix (`ParentProcessId` pointing at already-dead wrapper PIDs). First sweep attempt (with a `$Root`-substring filter) missed all 4, confirming the relative-path blind spot above; removing that filter caught and killed all 4 on the next `-Restart`.
- `.\run_all.ps1 -Restart` twice in a row, then inspected `Get-CimInstance Win32_Process` directly: exactly one `run_app.py`/`run_dispatcher.py`/`run_worker.py` triple, each a direct child of the launching shell (matching the recorded PIDs, no wrapper layer).
- `.\run_all.ps1 -Stop` followed by the same process inspection: zero survivors (previously this left orphans -- the actual regression this fix targets).
- Restarted the stack with `.\run_all.ps1`; live preflight and `GET /api/metrics` both confirmed against the freshly running process, including the `redis_queue` section from Checkpoint 83 (previously unverified live because the running process predated that change).
- `python -m unittest discover -s tests` passed 187 tests (unaffected -- this is a deployment script, not covered by the Python test suite).

Next:

- No Python test coverage exists for `run_all.ps1` itself (PowerShell, outside `python -m unittest`); CI's "Check stack launcher script" step only parses it, doesn't execute the process-management logic. Consider a lightweight PowerShell-based CI check if this script grows more logic.

## 2026-08-13 - Checkpoint 87: Recipe-Compatibility Freshness Checks, and a Real Worker Crash Bug Found Live

Implemented:

- Added `recipe_validation_freshness()` (`src/xingestion/releases/validation_records.py`), which flags per (capability binding recipe x validation type) whether the most recent `recipe_validation_record` still describes what's actually running: no record at all, a record whose `composition_hash` no longer matches the manifest's live recipe (someone edited the parser/operation/pagination composition without bumping `recipe_revision_id`), or a record that failed, are all "not fresh"; a matching, passing record is "fresh."
- Wired it into `health_report.py` (`recipe_validation_freshness` section) and `/api/metrics` (`live_server.py`), and added a non-blocking `recipe_validation_freshness` check to `run_supervisor_check.py`/`DeploymentSupervisorCheck` (WARN, never FAIL -- deliberately not a worker-side execution block, since gating live task processing on validation history is a much bigger behavior change than this checklist item calls for and risks silently halting a working pipeline).
- **Found and fixed a real, previously-unknown worker crash bug while live-verifying this feature.** The live worker died with an unhandled `ValueError` while processing real tasks. Root cause: in `LocalWorker._process_delivery`'s failure path (`local_worker.py`), when a task's execution lease is renewed or re-acquired by another delivery (a genuine fencing race -- e.g. this lease expired mid-execution and was reclaimed elsewhere) between this delivery's failure and its failure-handling `transition_task` write, that write uses the now-stale `lease_token`/`delivery_generation` and is correctly rejected by the ledger's fencing -- but the resulting second `ValueError` was never caught, unlike the equivalent race already handled at lease-acquisition time. It propagated all the way up through `run_worker.py`'s main loop and killed the entire worker process, silently halting all task processing until someone noticed and restarted it manually.
- Fixed by catching that `ValueError` and falling back to reading the task's current state from the ledger (mirroring the existing acquire-lease race handler), the same way a fencing loss is already handled everywhere else in this file.

Verified:

- `python -m compileall -q src tests run_*.py` passed.
- `python -m unittest discover -s tests` passed 194 tests, including 4 new `recipe_validation_freshness` unit tests (missing record, matching+passing, failed latest record, composition drift), 2 new supervision tests, an extended health-report assertion, and a new `test_worker_survives_lease_stolen_during_failure_handling` regression test in `test_local_worker.py`.
- Confirmed the regression test actually exercises the bug: temporarily reverted the fix and re-ran the test -- it raised an unhandled exception (a `dataclasses.FrozenInstanceError` from unittest's own traceback handling on the frozen `ProtocolError` dataclass, but confirming propagation past `_handle_failure` either way); reapplied the fix and the test passed cleanly.
- Live: `run_health_report.py` and `run_supervisor_check.py` against the real stack both show `recipe_validation_freshness: checked=2 all fresh`, correctly matching the release/recipe validated during Checkpoint 85/86's live testing.
- Live: restarted the worker (which had actually crashed from the bug above, confirmed dead via process inspection and a `ValueError`/`FrozenInstanceError`-adjacent traceback in `worker.err.log`) with the fix applied; it drained an 86-entry Redis stream backlog of orphaned deliveries (see below) without crashing, then settled to idle and stayed up.
- Discovered in the process: the orphaned-delivery backlog was caused by this session's own repeated `python -m unittest discover -s tests` runs -- `make_postgres_ledger()` truncates `capability_tasks`/`outbox_events` in the same default local Postgres database the live `run_all.ps1` stack uses, with no isolation between the two. Documented this as an explicit warning in the deployment runbook; did not change the test fixture's default DSN (a bigger, CI-affecting decision left for later).

Next:

- Consider giving `postgres_fixture.py`'s tests a dedicated local database/DSN instead of sharing the live dev stack's default, so running the suite no longer risks truncating a stack someone is actively using.
- Surface protocol drift reports when the approved recipe starts failing in production (remaining open item in this section).

## 2026-08-13 - Checkpoint 88: Fixed CI (Broken Since Checkpoint 83) and Postgres Test/Dev Isolation

Implemented:

- **Root-caused and fixed CI, which had been failing on every push since Checkpoint 83** (`gh run list`/`gh run view --log-failed` showed 4 straight failed runs, all with the identical `KeyError: 'stream_key'` in `test_health_report_writes_safe_operator_snapshot`). Cause: `redis_queue_stats()` (`src/xingestion/dispatch/redis_stream_stats.py`) called `XINFO GROUPS` on the stream key, which raises `ResponseError` on a key that has *never* been written to (unlike `XLEN`, which returns 0 for the same key) -- true on a fresh CI Postgres/Redis job where nothing has been dispatched yet, never true locally where the dev stack's Redis always already had a live stream. `build_health_report()`'s `_safe_section` caught the exception and returned `{"error": ..., "message": ...}` instead of stats, so the test's `saved["redis_queue"]["stream_key"]` lookup KeyError'd. Fixed by catching `redis.ResponseError` around the `XINFO GROUPS` call and treating a missing stream the same as a missing group (added `test_reports_empty_stats_when_stream_does_not_exist_at_all`).
  - Because the CI workflow's Postgres/Redis job runs each test file as a separate `run:` line in one bash step (which fails fast on the first non-zero exit), every file listed *after* `test_health_report.py` -- `test_support_export.py`, `test_northbound_api.py`, `test_preflight.py`, `test_investigation.py`, `test_outbox_operations.py`, and the newly-added `test_delivery_load.py` -- had never actually executed in CI since Checkpoint 83, despite all of Checkpoints 84-87's work landing in that window. Local `python -m unittest discover -s tests` runs never caught any of this because local discovery runs every file in one process regardless of an earlier file's failure.
- **Fixed the local Postgres test/dev data-isolation gap flagged in Checkpoint 87.** `tests/postgres_fixture.py`'s `DEFAULT_TEST_DSN` now points at a dedicated `xingestion_test` database instead of the same `xingestion` database `XINGESTION_POSTGRES_DSN` defaults to (the one `run_all.ps1`'s live stack uses) -- auto-created via `probe_reachable()` if missing (connects to the always-present `postgres` admin database, checks `pg_database`, issues `CREATE DATABASE` if needed). CI is unaffected: its workflow always sets `XINGESTION_TEST_POSTGRES_DSN` explicitly to the single-database service container, never relying on this Python-level default.
  - Three test files hardcoded the *old* shared-DSN literal directly into an `AppConfig(postgres_dsn=...)` used to open a second, independent Postgres pool for reading/writing real task data (`health_report.py`'s `_open_task_ledger`, `support_export.py`'s pool) -- separate from the `self.ledger = make_postgres_ledger()` used to set up each test's fixture data. Left as literals, these would have silently pointed at the *old* shared database after the fixture default moved, breaking the tests (data created via one DSN, read back via another). Fixed `test_health_report.py`, `test_support_export.py`, and `test_preflight.py`'s `_config()` default to use `postgres_fixture.test_dsn()` instead. Left `test_secrets.py`/`test_logging_config.py`'s hardcoded literals alone -- confirmed neither ever opens a real Postgres connection with it, it's just a required `AppConfig` field filler.

Verified:

- `python -m compileall -q src tests run_*.py` passed.
- `python -m unittest discover -s tests` passed 195 tests (194 + 1 new `redis_queue_stats` regression test).
- Live isolation check: snapshotted the live `xingestion` database's `capability_tasks` row count (1) before running the full local suite, ran it, and confirmed the count was still exactly 1 afterward -- previously this always dropped to 0 (or whatever the suite's own fixture data left behind). Confirmed `xingestion_test` was auto-created and holds its own independent state.
- `run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes` against the live stack: all 10 checks PASS, unaffected by the isolation change.
- Pushed both fixes and watched the resulting CI run to confirm the Postgres/Redis job goes green and every previously-unreached test file finally executes and passes.

Next:

- No further known CI or local-isolation issues; keep an eye on the first few CI runs after this checkpoint in case a test file that's never run in CI before surfaces something new.

## 2026-08-13 - Checkpoint 89: Recency-Windowed Protocol Drift Reports

Implemented:

- Added `ProtocolTelemetryStore.recent_attempts()` (`src/xingestion/telemetry/store.py`), returning the last N attempts (newest first, optionally filtered by `recipe_revision_id`) for a release -- the first thing in this codebase to query `protocol_attempts` as a recency-ordered window rather than a lifetime `GROUP BY` total. Uses the existing `idx_protocol_attempts_release_created` index, previously unused for trending.
- Added `build_protocol_drift_report()` (`src/xingestion/investigation.py`), which answers "is the approved recipe drifting in live production *right now*" -- deliberately distinct from the existing `build_release_risk_recommendation()`, which scores lifetime-cumulative error counts and never resets (a release with a handful of failures months ago stays flagged forever, and a release that just started failing is diluted by a long healthy history). The new report looks only at the most recent `window` attempts (default 20) against the *currently* approved recipe (filtered by `recipe_revision_id`, not just `release_id`, so a stale recipe rotation's history doesn't get attributed to the live one): `HIGH` severity if `OPERATION_NOT_FOUND`/`PARSER_FAILURE` appeared at all in that window, `MEDIUM` if the recent failure rate is >=40% or the recipe's `recipe_validation_freshness` (Checkpoint 87) is stale, otherwise healthy.
- Wired into `health_report.py` (`protocol_drift` section), `live_server.py` (`/api/metrics` and new `GET /api/releases/current/drift`), `preflight.py`'s API-shape contract check, and a new non-blocking `protocol_drift` `WARN`-only check in `run_supervisor_check.py`/`supervision.py` -- deliberately not a hard preflight/supervisor gate the way `release_risk`'s `QUARANTINE_RECOMMENDED` already is, since this signal is far more sensitive (fires on a single recent hard-signal occurrence, not 3+ lifetime) and gating startup/supervision on it risked blocking a deployment over one transient glitch.

Verified:

- `python -m compileall -q src tests run_*.py` passed.
- `python -m unittest discover -s tests` passed 207 tests, including 3 new `recent_attempts()` unit tests, 6 new `build_protocol_drift_report()` scenario tests (hard-signal, high failure rate, all-healthy, outside-window recency, stale-validation-only, no-attempts), 2 new supervision tests, an extended health-report assertion, and a new northbound API test for the `/api/releases/current/drift` route.
- Live: restarted the stack, confirmed `/api/releases/current/drift` returns 200 (previously 404 against the pre-restart process), and `run_health_report.py`/`run_supervisor_check.py` both show `protocol_drift` correctly computed against real historical telemetry -- 16 recent attempts, 2 `ValueError` failures (12.5%, from earlier session incidents), correctly reported as `drifting=false severity=LOW` since `ValueError` isn't a hard drift signal and the rate is well under the 40% threshold.

Next:

- `docs/TASKS.md`'s "Runtime and Drift" section is now fully checked off. Remaining open items are in "SEARCH_TWEETS Vertical Slice," "Durable Execution and Delivery" (the single-node-vs-managed-infra decision), and "Production Hardening."

## 2026-08-13 - Checkpoint 90: Cursor-Loop Investigation Evidence, and a Real Cross-Page Loop-Detection Bug Found and Fixed

Implemented:

- Added `src/xingestion/pagination_chain.py`: `walk_pagination_chain(ledger, task)` walks a task's continuation lineage backward via `request_json.payload.pagination_parent_task_id` (set by `LocalWorker._queue_continuation_if_needed`), returning each ancestor page's task ID, page number, cursor, and state, oldest first. Stops on a missing or cyclic parent reference rather than raising (diagnostic-only, defensive against a corrupted chain). Also exports `is_pagination_error_class()` for the three `PAGINATION_*` error classes.
- **Found and fixed a real, previously-undetectable bug while building this.** `validate_search_tweets_pagination()` (`xprotocol/runtime/search_tweets.py`) has always accepted a `seen_cursors` parameter for exactly this purpose -- but `LocalWorker._validate_page_pagination()` never populated it, only ever passing `current_cursor` (the cursor just used for the failing page). That means a `PAGINATION_CURSOR_LOOP` could only ever fire when a page's returned cursor exactly repeated the *immediately previous* page's cursor -- a loop back to any *older* page's cursor (e.g. page 5 looping back to page 2's cursor) went completely undetected, and the worker would just keep creating continuation tasks up to `max_pages` instead of ever raising the error. Fixed `_validate_page_pagination()` to pass `seen_cursors` built from `walk_pagination_chain()`.
- Wired `walk_pagination_chain()` into `build_protocol_drift_package()` (`investigation.py`): every investigation package now includes a `pagination_chain` section (`is_pagination_failure`, `root_task_id`, `chain_length`, and the ordered list of prior pages with cursors), regardless of the failure type -- empty/`false` for non-pagination failures, populated for pagination ones. `write_failed_task_export`/`run_failed_task_export.py` pick this up automatically since they wrap `build_protocol_drift_package` verbatim. Added a dedicated diagnosis hint for `PAGINATION_*` error classes pointing at the new field.

Verified:

- `python -m compileall -q src tests run_*.py` passed.
- `python -m unittest discover -s tests` passed 214 tests: 5 new `walk_pagination_chain`/`is_pagination_error_class` unit tests (using a lightweight fake ledger, no Postgres needed), 1 new `test_investigation.py` test asserting `pagination_chain` evidence for a real two-page continuation chain, and 1 new `test_local_worker.py` regression test.
- Confirmed the regression test actually exercises the bug: built a 3-page chain where page 3's returned cursor matches page 2's (not page 3's own `current_cursor`) via a new `SequencedCursorTransport`; temporarily reverted the `seen_cursors` fix and re-ran -- page 3 silently completed as `DONE` instead of being caught (proving the described gap was real); reapplied the fix and page 3 correctly `DEAD_LETTER`s with `PAGINATION_CURSOR_LOOP`.
- Live: restarted the stack, `POST /api/tasks/{task_id}/investigate` against a real dead-lettered task returns a well-formed `pagination_chain` section (`is_pagination_failure=false, chain_length=0` for this particular non-pagination failure, confirming the field is always present and correctly computed against the real Postgres ledger).

Next:
- `docs/TASKS.md`'s "SEARCH_TWEETS Vertical Slice" section still has two open items: expanding search request inputs to cover more stable contract fields, and validating the full acquisition recipe as one release-bound unit.

## 2026-08-13 - Checkpoint 91: Closed "Expand Search Request Inputs" -- No Spec Gap Found

Investigated (no code changes):

- Checked `FINAL_PRODUCT_SPEC.md`'s SEARCH_TWEETS "Inputs" list against `SearchTweetsInput` (`src/xingestion/capabilities/models.py`) before writing any new fields. The spec's example lists exactly `query`, `product`, `cursor`, `page_size` -- `SearchTweetsInput` already has all four; there is no unimplemented spec-named field to add.
- Also checked whether the pinned `SearchTimeline` GraphQL operation (`protocol_releases/search_tweets.candidate.json`) has variable slots for filters a caller might reasonably want (language, date range, result type, exclude replies): it does not. `build_search_timeline_request()` only ever forwards `rawQuery`/`count`/`querySource`/`product`/`cursor` plus two static feature-flag booleans. Any such filter is only expressible today by embedding X's own search operators directly in the `query` string (e.g. `"india lang:en since:2026-01-01"`), which already works with zero code changes -- `tests/test_capability_planner.py:30` already demonstrates this.
- Decided with the user not to invent new structured convenience fields (e.g. a `language`/`since`/`until` parameter that compiles down to query-string operators) since the spec doesn't call for them and it would be scope beyond what this checklist item asked for. Checked the item off in `docs/TASKS.md` with a note explaining why, so the reasoning doesn't need to be re-derived later.

Next:
- `docs/TASKS.md`'s "SEARCH_TWEETS Vertical Slice" section has one item left: validating the full acquisition recipe as a single release-bound unit.

## 2026-08-13 - Checkpoint 92: Recipe Binding Consistency -- Validate the Recipe as One Bound Unit

Implemented:

- Investigated first (background exploration agent) whether existing validation already covers "the full recipe as one unit" before writing anything: fixture validation only ever exercises the parser against a stored JSON payload; capture/replay comparison only re-parses two already-stored files; the one code path that builds a real request from the full composed recipe (`_run_direct_replay_for_capture`) runs only via the operator-triggered validation-run route, never as part of release-approval gating. Most notably: `AcquisitionRecipeRevision.auth_profile.required_material` and `.transaction_profile.required_headers` are pure declarative metadata -- nothing anywhere checks them against what `build_search_timeline_request()` (`xprotocol/runtime/search_tweets.py`) actually does. A mismatch here (e.g. code drops a header the manifest still declares required, or vice versa) would only ever surface as a live 401/rejected request in production.
- Added `validate_recipe_binding(recipe)` (`xprotocol/runtime/search_tweets.py`): builds one real (probe-credentialed) `ProtocolHttpRequest` from the recipe's `operation`/`auth_profile`/`transaction_profile` together via the actual request builder, then checks `auth_profile.required_material` against `WebSessionAuth`'s real dataclass fields (introspected, not hardcoded, so it stays correct if `WebSessionAuth` ever changes) and every declared `transaction_profile.required_headers` entry against the headers the builder actually set. Returns a tuple of human-readable inconsistency strings; empty means the recipe's components are genuinely consistent with each other, not just individually plausible.
- Wired into `build_promotion_safety_report()` (`releases/promotion.py`) as a new `recipe_binding_consistency` check, run for every binding in the manifest, HIGH severity (blocks normal approval) on any inconsistency -- alongside `manifest_present`, `release_health_allows_execution`, `fixture_validation`, and `capture_replay_comparison`.

Verified:

- `python -m compileall -q src tests run_*.py` passed.
- `python -m unittest discover -s tests` passed 219 tests: 4 new `validate_recipe_binding` unit tests (passes for the real pinned recipe; flags an undeclared-but-required header the builder doesn't send; flags auth material missing from what `WebSessionAuth` needs; flags auth material declared that `WebSessionAuth` doesn't have), and 1 new `test_release_promotion.py` test confirming a mutated (internally inconsistent) recipe blocks promotion safety with a message naming the specific bad header.
- Confirmed against the real pinned manifest directly (`PYTHONPATH=src python -c "..."`) that `validate_recipe_binding()` returns zero problems -- the current recipe's declared metadata genuinely does match runtime behavior today, this wasn't catching an existing bug, just closing a gap that had no safety net.
- Live: `run_releases.py check xrev-search-tweets-2026-08-10-candidate-1 --json` shows the new `recipe_binding_consistency` check passing alongside the existing ones; restarted the stack and `run_supervisor_check.py` confirms the full stack still healthy.

Next:
- `docs/TASKS.md`'s "SEARCH_TWEETS Vertical Slice" section is now fully checked off. Remaining open items are the single-node-vs-managed-infra decision (Durable Execution and Delivery, the user's call) and the "Production Hardening" section (draining stale outbox backlog, connection-pool/`LISTEN`/`NOTIFY` tuning, replacing the hand-rolled Postgres migration runner, the next capability vertical slice).

## 2026-08-13 - Checkpoint 93: Redis Stream Backlog Reconciliation, After Ruling Out a Postgres-Side False Start

Implemented:

- Read the full `FINAL_PRODUCT_SPEC.md` end to end against the current implementation before starting this checkpoint (user asked to always cross-check the spec, not just `docs/TASKS.md`, going forward -- saved as a standing memory preference). Found and now tracks four larger spec-flagged gaps `docs/TASKS.md` never listed at all: monitoring subscriptions (spec §28, zero implementation), a genuinely stable northbound API (spec §30, today's is the trusted operator console), broader canonical data model (spec §19, tweets/engagement only), and a real release rollout/rollback lifecycle (spec §26, canary/automated-failover state machine vs. today's manual health toggling). Added as a new tracked section, deliberately not started -- user chose to keep polishing the smaller existing checklist items first.
- **Started, then reverted, a Postgres-side `reconcile_outbox_backlog()`** targeting "outbox events referencing a deleted task." Verified empirically against the real schema that this is structurally impossible: `outbox_events.task_id` has a `REFERENCES capability_tasks(task_id)` foreign key with no `CASCADE`, so Postgres itself refuses any `DELETE` that would orphan an unpublished outbox row. Even the actual incident that motivated this checklist item (this session's earlier test-pollution bug) didn't leave Postgres-side orphans -- a `TRUNCATE ... CASCADE` empties both tables together. The orphaning was always a Redis-vs-Postgres cross-system problem, never a Postgres-internal one. Reverted the Postgres-side code (`git checkout --` on the 4 files touched) before it was committed, rather than shipping dead code for an impossible scenario.
- Added `reconcile_redis_stream_backlog()` (`src/xingestion/dispatch/redis_stream_stats.py`) instead: enumerates up to `limit` stream entries via `XRANGE`, cross-references each entry's `task_id` against Postgres (the durable authority), and reports/optionally `XDEL`s ones whose task no longer exists -- the actual gap, since Redis has no referential integrity with Postgres and `apply_retention()` legitimately deletes terminal tasks that could still have an undelivered stream entry sitting behind a stalled/backlogged consumer group.
- Wired into `run_outbox.py` (`--reconcile-stream`, `--apply`, `--stream-limit`, dry-run by default) and a new `POST /api/outbox/reconcile-stream` route (admin-required, `{"limit": 500, "dry_run": true}` body, same safe-by-default posture).

Verified:

- `python -m compileall -q src tests run_*.py` passed.
- `python -m unittest discover -s tests` passed 225 tests: 5 new `reconcile_redis_stream_backlog` unit tests (no orphans, dry-run reports without deleting, apply deletes only orphans, ignores entries with no `task_id` field, rejects non-positive limit) and 1 new northbound API route test.
- **Found a real, still-present problem on the live stack while validating this against production data**: `python run_outbox.py --reconcile-stream --json` found 102 of 103 scanned entries in the live `xingestion:capability-tasks` stream were orphaned -- accumulated ghosts from this session's several pre-fix test-pollution incidents (Checkpoint 88 fixed the root cause; these were leftovers from before that fix landed, message IDs spanning the entire session's timestamp range). Confirmed with the user before applying (destructive Redis action), then ran `--apply`: `deleted_entries=102`. Re-ran reconcile and `run_supervisor_check.py` afterward -- clean stream, all 10 checks `PASS`.

Next:
- `docs/TASKS.md`'s "Production Hardening" section has three items left: expand monitoring/release-risk handling around the approved route, connection-pool/`LISTEN`/`NOTIFY` tuning, and replacing the hand-rolled Postgres migration runner -- plus the single-node-vs-managed-infra decision and the four newly-tracked spec-flagged gaps.

## 2026-08-13 - Checkpoint 94: Deeper Spec-Gap Pass, and a New End-to-End Flow Document

Implemented:

- Went through `FINAL_PRODUCT_SPEC.md` section by section a second, deeper time (the earlier pass in Checkpoint 93 only found the four largest un-started subsystems). Added seven more specific, concrete gaps to `docs/TASKS.md`'s "Spec-Flagged Gaps" section, each citing its exact spec section: the typed protocol error taxonomy is 9-of-24 implemented (`errors.py`'s `ERROR_PROFILES`); there's no automated sanitized-fixture pipeline (spec §32 describes `Automated Sanitization -> Secret Scan -> Human Verification -> VERIFIED_SANITIZED`, none of which exists in code); no distinct `Account` entity separate from `SessionArtifact` (spec §10.1-10.2, today's `SessionRecord.account_label` is just a string); several spec-listed observability metrics aren't tracked (`session_concurrency`, a live `schema_fingerprint` signal, `normalization_lag`, `monitor_lag`); X-rev validation lifecycle stages 4-8 aren't built (spec §24, only stage 3 -- parser+pagination+full recipe validation -- exists, completed this session); and 10 of 11 spec-listed capabilities don't exist (spec §5, only `SEARCH_TWEETS`).
- Added `docs/SYSTEM_FLOW.md`: a new, from-scratch document explaining how the system actually works today, end to end, for a reader with no prior context -- distinct from `CURRENT_STAGE.md` (a point-in-time spec-coverage scorecard) and `WORKLOG.md` (a chronological build history). Ten sections, each with Mermaid diagrams grounded in real code paths built and verified this session: the big-picture architecture; the full task lifecycle from API call to canonical storage (capability request -> transactional outbox -> dispatcher -> Redis Streams -> worker -> X request -> parser -> canonical store); pagination as a chain of linked tasks with cross-page cursor-loop detection; failure handling (retry state machine, crash/lease-reclaim sequence diagram, the Redis-vs-Postgres reconciliation gap and why the mirror-image Postgres-side version is structurally impossible); the three-signal explanation of `recipe_validation_freshness` vs. `protocol_drift` vs. `release_risk` (why three, not one -- each answers a genuinely different question); the seven-check promotion safety gate in order; the investigation package's `pagination_chain` evidence; an operator-tooling map of every `run_*.py` script; and a data-model summary table across Postgres/Redis/SQLite.
- Linked the new document from `README.md`'s doc index as the recommended starting point for a new reader.

Verified:

- Read every diagram back for Mermaid syntax risk (unmatched brackets, node-ID collisions across a single diagram block, unquoted punctuation) before finalizing -- none found; existing quoting conventions (quoting any node label containing commas, multi-clause sentences, or `/` in edge labels) were applied consistently throughout.
- Cross-checked every concrete claim against the actual source before writing it, rather than from memory: `canonical/store.py`'s exact table/column names, the promotion safety checks' exact order and names (`manifest_present -> manifest_release_match -> release_health_allows_execution -> bindings_present -> recipe_binding_consistency -> fixture_validation -> capture_replay_comparison`), and the error-taxonomy gap count, all read directly from source for this document.

Next:
- No code changed this checkpoint (docs only) -- next work remains `docs/TASKS.md`'s open "Production Hardening" items and the newly-expanded spec-gap list.

## 2026-08-13 - Checkpoint 95: Approved Search-Route Monitoring Hardening

Implemented:

- Added a first-class `search_route_monitoring` signal that summarizes the currently approved search route for the active release, including the target network context, any matching route telemetry, and the route-level recommendation when the route is unhealthy.
- Wired the new signal into `/api/metrics`, the operator health report, the frontend metrics strip, and `run_supervisor_check.py` so route remediation now shows up in the real operator path instead of only being implicit in the broader network-health view.
- Hardened preflight API-shape checks to require the new metric key.
- Added supervision coverage for both route-remediation warnings and route-quarantine failures.

Verified:

- `./.venv/bin/python -m compileall -q src tests`
- `./.venv/bin/python -m unittest tests.test_investigation tests.test_supervision tests.test_health_report tests.test_preflight tests.test_northbound_api`

Next:

- Remaining open items in `docs/TASKS.md` are now the single-node-vs-managed-infra decision, connection-pool/`LISTEN`/`NOTIFY` tuning, replacing the hand-rolled Postgres migration runner, and the next capability vertical slice.

## 2026-08-13 - Checkpoint 96: Single-Node Dispatcher Wakeups

Implemented:

- Added a Postgres `LISTEN`/`NOTIFY` wake path for the outbox dispatcher on a dedicated channel, while keeping the existing poll loop as a fallback if the notify listener is unavailable.
- Added a new Postgres trigger migration on `outbox_events` so committed inserts immediately emit a wakeup notification carrying the `event_id`, `task_id`, and `created_at` payload.
- Added a dispatcher helper that drains all currently pending outbox rows in one wake cycle before returning to the listener/poll loop.
- Exposed the new notification listener and channel from the dispatch package for reuse and testing.
- Added a live integration test that confirms an outbox insert emits a dispatcher wake notification after commit.

Verified:

- `./.venv/bin/python -m compileall -q src tests run_dispatcher.py`
- `./.venv/bin/python -m unittest tests.test_local_worker tests.test_delivery_load`

Next:

- The remaining open items in `docs/TASKS.md` are the structured Postgres migration tooling cleanup and the next capability vertical slice after `SEARCH_TWEETS`.

## 2026-08-13 - Checkpoint 97: Merged PR #6, Fixed a Stale Test It Broke, Updated Docs

Implemented:

- Merged GitHub PR #6 ("Harden search route monitoring," already merged upstream by the repo owner via GitHub -- Checkpoints 95-96 above are that PR's own worklog entries) into the local `main` branch with `git merge --ff-only` (clean fast-forward, no local commits diverged, so no conflicts possible).
- Verified the merge instead of assuming it was safe: ran `python -m compileall` (clean) and the full test suite, which found a real break the PR's own narrower verification (`python -m unittest tests.test_local_worker tests.test_delivery_load`, per Checkpoint 96) hadn't caught -- `tests/test_postgres_migration_runner.py`'s `EXPECTED_MIGRATIONS = ("001",)` was never updated for the PR's new `002_outbox_notify_trigger.sql` migration, so `test_applies_baseline_migration_once` and `test_status_survives_a_pool_connection_previously_used_with_dict_row` both failed. Fixed to `("001", "002")`.
- Updated `docs/CURRENT_STAGE.md` (date line, Production Control Plane bullet for the new `LISTEN`/`NOTIFY` wake path, Release Health bullet for `search_route_monitoring`, and the now-partially-stale "Next Recommended Work" `LISTEN`/`NOTIFY` mention) and `docs/deployment_runbook.md` (dispatcher wake-path mechanics including the exact trigger/migration/channel/env-var names, and `search_route_monitoring`'s relationship to `release_risk`/network-route recommendations) to reflect what the merge actually added.
- Updated `docs/SYSTEM_FLOW.md` (written last checkpoint, before this merge existed) for accuracy: §3.2's dispatcher diagram was describing pure fixed-interval polling, which is no longer true -- redrawn to show the `LISTEN`/`NOTIFY` trigger as the primary wake path with polling as an explicit fallback, and corrected the "drains everything in one wake" behavior. §5 now explains `search_route_monitoring` as a presentation layer over the existing `release_risk`/network-route signals scoped to one route, not a fourth independent signal (avoiding contradicting that section's central "three signals, deliberately not more" point).

Verified:

- `python -m compileall -q src tests run_*.py` passed.
- `python -m unittest discover -s tests` passed 229 tests (0 skipped beyond the usual 3 opt-in load tests) after the `EXPECTED_MIGRATIONS` fix.
- `python run_postgres_migrations.py` applied migration `002` to the real local database cleanly.
- Live: restarted the stack; `dispatcher.err.log` confirms `"dispatcher listening on postgres channel=xingestion_outbox_events for outbox wakeups"` (not the polling-fallback warning); `run_supervisor_check.py` shows all 11 checks `PASS` including the new `search_route_monitoring` check; `run_smoke.py --submit "india lang:en" --wait 60` completed a real task end to end (`state=DONE tweets=21`) through the new notify-driven dispatch path.
- Confirmed the fix was genuinely necessary, not local-only flakiness: PR #6's own merge-commit CI run (triggered automatically by the GitHub-side merge, independent of anything done in this session) failed on GitHub Actions with the identical `EXPECTED_MIGRATIONS` assertion error; the very next push (this checkpoint's fix) went green.

Next:

- `docs/TASKS.md`'s "Production Hardening" section has one item left: replacing the hand-rolled Postgres migration runner with structured migration tooling. Otherwise remaining work is the single-node-vs-managed-infra decision, the next capability vertical slice, and the spec-flagged gaps list.

## 2026-08-14 - Checkpoint 98: TWEET_BY_ID Vertical Slice (Architecture Complete, Operation ID Still a Placeholder)

Implemented:

- Added the full `TWEET_BY_ID` capability slice: `xprotocol/runtime/tweet_by_id.py` (request builder, `acquire_tweet_by_id()`, `parse_tweet_by_id_result()`, `validate_tweet_by_id_recipe_binding()` self-check mirroring `search_tweets.validate_recipe_binding()`), a new `DRAFT`/`INFERRED` recipe binding in `protocol_releases/search_tweets.candidate.json` targeting X's `TweetResultByRestId` GraphQL operation, a `single_page` pagination strategy (degenerate -- one object, no continuation), `TweetByIdInput`/`CapabilityInputPayload` in `capabilities/models.py`, worker dispatch in `local_worker.py` (wraps the single-tweet result as a one-element, no-continuation `SearchTweetsPage` so canonical ingest and result-serialization work unmodified), a `POST /api/tweet-by-id` endpoint plus generic-payload dispatch in `/api/capability-tasks`, and two new typed errors (`OBJECT_NOT_FOUND`, `ACCESS_NOT_AUTHORIZED`).
- Extracted `TweetRecord`/`make_tweet_record()`/`merge_tweet_records()` out of `search_tweets.py` into a shared `xprotocol/runtime/tweet_fields.py` (pure code-move, confirmed via diff review to be behavior-preserving) since both capabilities parse the same nested `legacy`/`core`/`rest_id` tweet shape.
- Parameterized `record_recipe_validation_results()` with a `capability_id` filter so `SEARCH_TWEETS` fixture-validation outcomes stop being incorrectly recorded against `TWEET_BY_ID`'s untested recipe now that the manifest has two bindings.
- This work was already complete and uncommitted in the working tree at the start of this checkpoint (not authored in this session) -- treated it the same as an incoming PR: read every changed file, confirmed the `search_tweets.py` extraction was behavior-preserving, then ran the full suite before trusting it.

Fixed:

- `tests/test_health_report.py`'s `test_health_report_writes_safe_operator_snapshot` asserted every `recipe_validation_freshness` entry matched `manifest.bindings[0]`'s recipe revision id -- true when the manifest had one binding, false now that it has two (`SEARCH_TWEETS` and `TWEET_BY_ID`). Fixed to check membership against the set of all bindings' revision ids instead. Same category of bug as Checkpoint 97's `EXPECTED_MIGRATIONS` staleness: a test that hardcoded an assumption the manifest was single-capability.

Not done:

- The recipe's `operation_id` is a placeholder (`REPLACE_WITH_CAPTURED_TWEET_RESULT_BY_REST_ID_OPERATION_ID`) -- no live browser capture of X's real `TweetResultByRestId` operation ID exists yet. This requires an authenticated browser session against x.com to capture, which needs a live account and is out of scope for an unattended session to perform. Until that capture happens and the binding passes fixture/capture-replay validation the way `SEARCH_TWEETS`'s did, `docs/TASKS.md` correctly marks this item `[~]` (in progress), not `[x]`.

Verified:

- `python -m compileall -q src tests run_*.py` passed.
- `python -m unittest discover -s tests` passed 243 tests (skipped=3) after the `test_health_report.py` fix -- up from 229 (14 new tests: `tests/test_tweet_by_id_runtime.py` plus additions to `test_capability_planner.py`, `test_local_worker.py`, `test_northbound_api.py`, `test_protocol_models.py`, `test_release_store.py`).

Next:

- Capture `TweetResultByRestId`'s real operation ID via an authenticated browser session, replace the placeholder, and run it through the same fixture/capture-replay validation pipeline `SEARCH_TWEETS` went through before it can flip to `[x]`. Otherwise unchanged: migration tooling and the spec-gap list.

## 2026-08-14 - Checkpoint 99: Documented the GraphQL Operation ID Capture Procedure

Implemented:

- Added a "Capturing a New GraphQL Operation ID (New Capability Onboarding)" section to `docs/deployment_runbook.md`, between "Operator Controls" and "Verification Before Release": a step-by-step DevTools procedure (sign in, Network tab, filter to Fetch/XHR + `graphql`, trigger the specific UI action, read the operation ID out of the request URL, copy-as-cURL to cross-check `feature_bundle`/`transaction_profile` against what the manifest declares) plus how to plug the captured value into `protocol_releases/search_tweets.candidate.json` and update `DRAFT`/`INFERRED` status markers. Written generically (applies to any future capability's operation ID, not just this one) but with `TweetResultByRestId`-specific guidance on which UI action actually triggers that operation versus the similarly-shaped `TweetDetail` operation.
- No code changed -- this is deliberately a manual, operator-driven procedure requiring the operator's own authenticated X session; nothing here is meant to be automated (see `playground/Twitter Research.md` §21 on why session credentials specifically must never be handled by tooling that could leak or commit them).
- Cross-referenced the new runbook section from `docs/TASKS.md`'s `TWEET_BY_ID` item, `docs/CURRENT_STAGE.md`'s "Next Recommended Work" item 2, and `docs/SYSTEM_FLOW.md` §1's capability-status paragraph, so anyone landing on any of those already knows where the how-to lives instead of re-deriving it.

Verified:

- `python -m compileall -q src tests run_*.py` and `python -m unittest discover -s tests` (243 passed, skipped=3) -- both a no-op safety check since this checkpoint is docs-only.

Next:

- Once an operator performs the capture and the placeholder `operation_id` is replaced, `protocol_validation.py` still needs to become capability-parameterized (see `docs/TASKS.md`) before `TWEET_BY_ID` can pass capture-replay validation and reach `APPROVED`. Otherwise unchanged: migration tooling and the spec-gap list.
