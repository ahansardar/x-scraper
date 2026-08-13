# Current Stage Against FINAL_PRODUCT_SPEC

Date: 2026-08-13 (updated: persisted recipe-level release validation records alongside JSON validation report artifacts)

This document records where `F:\x-scraper` currently stands relative to `FINAL_PRODUCT_SPEC.md`, and how the implementation reached this stage.

## Current Label

The project is currently a production-oriented local vertical slice for `SEARCH_TWEETS`.

It is not yet the complete final product described in `FINAL_PRODUCT_SPEC.md`. The final spec describes two responsibilities:

- protocol runtime work: protocol research, validation, request construction, parsing, pagination, and approved protocol releases.
- production ingestion work: durable orchestration, retries, accounts/sessions/network allocation, canonical data, APIs, monitoring, and operations.

This repository keeps both responsibilities in one visible source package:

- `src/xingestion/` contains the product source tree.
- `src/xingestion/xprotocol/` contains the internal protocol/runtime foundation.
- `playground/` contains the older experimental GraphQL scripts and research artifacts.

## Current Verified State

Latest verified state:

- See `docs/WORKLOG.md` for the latest checkpoint-level verification and commit history.
- GitHub Actions CI runs the main suite on Windows for Python 3.11 and 3.12, plus a dedicated Postgres/Redis-backed job on Ubuntu (service containers) for Python 3.11 and 3.12.
- Local startup directory readiness passes.
- Local Postgres and Redis run via `docker compose up -d` (see `docker-compose.yml`); the application itself (web, worker, dispatcher) is never containerized.
- Default local storage is under `F:\x-scraper\data`.

Important runtime locations:

- Task ledger and transactional outbox: PostgreSQL (`XINGESTION_POSTGRES_DSN`, default local port `55432`)
- Outbox delivery: Redis Streams (`XINGESTION_REDIS_URL`) -- reconstructable from Postgres, never authoritative
- SQLite session/canonical/release/telemetry/reprocess state: `F:\x-scraper\data\tasks.sqlite3`
- Raw evidence: `F:\x-scraper\data\raw_evidence`
- Logs: `F:\x-scraper\data\logs`
- Health reports: `F:\x-scraper\data\reports`
- Support exports: `F:\x-scraper\data\support_exports`
- Release promotion audits: `F:\x-scraper\data\release_promotions`

Known current operational signal:

- The task ledger/outbox migration to PostgreSQL + Redis Streams (this document's prior "next infrastructure step") is complete: `PostgresTaskLedger`, `RedisOutboxDispatcher`, and a consumer-group-based `LocalWorker` are live end to end, verified against a real `run_dispatcher.py` process plus a simulated worker-crash/PEL-reclaim scenario.
- `run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes` now also requires `run_dispatcher.py` in the process table alongside `run_app.py`/`run_worker.py`.

## What Is Implemented

### Spec-Aligned Capability Boundary

Implemented:

- Stable capability request shape for `SEARCH_TWEETS`.
- Generic `POST /api/capability-tasks`.
- UI shortcut `POST /api/search-tweets`.
- Capability planner boundary.
- Approved protocol release pointer in SQLite, resolved to one exact manifest from `protocol_releases/`.
- Operator release inventory and approval through `run_releases.py`, `GET /api/releases`, and `POST /api/releases/approve`.
- Promotion safety checks before normal approval, including manifest sanity, release health, fixture validation, and capture/replay comparison, each persisted as a first-class `recipe_validation_record` (`release_id`, `recipe_revision_id`, `composition_hash`, `runtime_version`) alongside the existing JSON report artifacts.
- Redacted release promotion audit packages for checks, blocked approvals, normal approvals, and forced approvals, exposed through `run_releases.py audits`, `GET /api/releases/audits`, downloads, retention cleanup, and the frontend Promotion Trail.
- Backpressure before task creation through `XINGESTION_MAX_ACTIVE_TASKS_PER_CAPABILITY`.

Spec relevance:

- Matches the spec principle that production clients request capabilities, not raw X endpoint details.
- Current scope is one capability, not the full capability family listed in the spec.

### Protocol Runtime Foundation

Implemented:

- SearchTweets request/runtime model.
- One-attempt transport boundary.
- Raw evidence sink protocol and file-backed raw evidence sink.
- Parser for protocol-normalized tweet records.
- Pagination cursor extraction for the current search path.
- Protocol release manifest and revision-style structures.
- Capture-vs-direct-replay validator for replayable raw evidence.

Spec relevance:

- Aligns with the spec's raw-first, one-attempt, protocol-owned request/parser boundary.
- Not yet a complete protocol authority with full research workbench, historical registry, complete validation lifecycle, and broad drift intelligence.

### Production Control Plane

Implemented:

- Durable task ledger using PostgreSQL (`PostgresTaskLedger`), single-node local instance via Docker Compose.
- Task states including created, enqueued, running, retry scheduled, done, dead letter, cancelled.
- Transactional outbox table in Postgres, committed atomically with task creation/replay.
- `RedisOutboxDispatcher`: publishes committed-but-undelivered outbox rows to a Redis stream (XADD before marking published, so a crash between the two produces a harmless duplicate delivery, never a lost one).
- Consumer-group-based `LocalWorker`: reads via `XREADGROUP`, acquires a fenced Postgres execution lease, executes, and only `XACK`s after the Postgres transition commits. Stale pending deliveries (crashed workers) are reclaimed via periodic `XAUTOCLAIM`, independent of Postgres lease expiry as a second, deliberately uncoordinated safety net.
- Idempotent task creation.
- Replay lineage for dead-letter tasks.
- Cancel, replay, reprocess, investigate, and export controls.

Spec relevance:

- Implements the spec's durable task lifecycle, transactional outbox, PostgreSQL-as-durable-authority, and Redis-Streams-as-reconstructable-delivery model, with fencing by task identity, delivery generation, and lease token.
- This is a single-node local Postgres/Redis instance (Docker Compose), not a managed/clustered/HA production deployment -- no connection pooling tuned for scale, no Postgres replication, no Redis Sentinel/Cluster.

### Sessions, Auth, and Network

Implemented:

- Session metadata stored without raw secret values.
- Default local session references `.env` values through a credential reference.
- Validated network policy metadata for session routes and worker selection.
- Active-release route health statistics and remediation recommendations.
- Session health states and health transitions.
- Session leases with expiry.
- Session restore/disable operator controls.
- Rate/auth-related session health behavior.
- Safe session attempt visibility: attempts, successes, failures, last attempt, last success, last error.

Spec relevance:

- Matches the spec's separation of session metadata, credential references, health, and leases.
- Not yet a full production account and network allocation plane; the current implementation has validated local route metadata, worker filtering, route health, and remediation guidance, not managed proxy/VPN provisioning.

### Raw Evidence, Canonical Data, and Reprocessing

Implemented:

- Raw X responses are written before parsing.
- Raw evidence references are attached to results.
- Canonical tweet rows are stored.
- Engagement observations are stored over time.
- Reprocessing can parse stored raw evidence again without recollecting from X.
- Output includes likes, views, reposts, and replies where available in the response.

Spec relevance:

- Matches the raw-first and reprocessing principles.
- Canonical data is still limited mainly to tweets and engagement observations; the full spec calls for users, lists, communities, relationship edges, profile observations, monitoring data, and more advanced normalization semantics.

### Release Health and Protocol Drift Operations

Implemented:

- Current release health storage.
- Release risk recommendations.
- Quarantine and activate controls.
- Approval controls that reload the live planner/worker for future tasks.
- Protocol telemetry attempts.
- Runtime error classification by class, severity, scope, retryability, and operator action.
- Investigation packages for failed tasks.
- Failed-task support packages for handoff.

Spec relevance:

- Supports the spec's failure isolation and protocol drift feedback principles.
- Not yet full release promotion, canary rollout, rollback automation, or validated multi-release failover.

### Operator Support Exports

Implemented:

- `POST /api/tasks/{task_id}/export`
- `GET /api/support-exports`
- `GET /api/support-exports/{file_name}`
- protected `GET /api/support-exports/{file_name}/download`
- protected `POST /api/support-exports/retention`
- `run_failed_task_export.py`
- Safe filename-only export reads and downloads.
- Redaction metadata and no raw secret inclusion.

Spec relevance:

- Supports safe investigation handoff and secret-free diagnostics.
- This is stronger than a demo path and is useful for deployment operations.

### Frontend Console

Implemented:

- Live acquisition form.
- Execution flow view.
- Operations panel.
- Startup readiness panel.
- Sessions panel.
- Metrics panel.
- Needs Attention panel for failed/retryable tasks.
- Support Exports panel with view/download/cleanup.
- Latest Output panel with real parsed output.
- Task ledger panel.
- Non-JSON API error reporting.

Spec relevance:

- Provides an operator surface for the current vertical slice.
- It is not yet the full analytics/monitoring product described by the final spec.

### Deployment and Operations

Implemented:

- Docker Compose for local Postgres + Redis infrastructure only; the application processes (web, worker, dispatcher) remain plain, uncontainerized Python.
- `.env`-driven configuration.
- Persistent data directory override via `XINGESTION_DATA_DIR`.
- Migrations for both stores: `run_migrations.py` (SQLite), `run_postgres_migrations.py` (Postgres, hand-rolled runner using `psycopg`, no ORM/Alembic dependency).
- Startup check command: `run_startup_check.py`.
- Preflight command: `run_preflight.py`, now including Postgres and Redis reachability checks.
- Smoke command: `run_smoke.py`.
- Supervisor check command: `run_supervisor_check.py`, now expecting `run_dispatcher.py` in the process table alongside web/worker.
- Health report export: `run_health_report.py`.
- Rotating logs.
- Retention controls.
- GitHub Actions CI: Windows matrix (Python 3.11/3.12) for the main suite, plus an Ubuntu job with Postgres/Redis service containers (Python 3.11/3.12) for the Postgres/Redis-backed test suites.

Spec relevance:

- Covers a meaningful part of the spec's operations/deployment hardening requirement.
- Still missing scale, chaos, soak, capacity testing, SLOs, and production infrastructure certification.

## How We Got Here

The current stage was built incrementally rather than as one large unverified rewrite.

### 1. Moved Historical Work to Playground

The older GraphQL scripts and exploratory artifacts were moved under `playground/`.

Reason:

- The final spec treats `x-scraper` history as research/prototype origin.
- New production code needed a cleaner internal boundary between protocol runtime and ingestion control plane without presenting two separate source packages.

### 2. Built Protocol Runtime Foundations

Implemented under `src/xingestion/xprotocol/`:

- protocol release/revision models;
- SearchTweets request builder/runtime concepts;
- one-attempt transport boundary;
- parser and pagination extraction;
- raw evidence sink interface and file implementation;
- typed protocol errors.

Reason:

- The spec requires X-specific request construction, parsing, and pagination to live behind a protocol runtime boundary rather than being spread through production code.

### 3. Built Product Task Control Plane

Implemented under `src/xingestion/`:

- capability requests;
- planner;
- task ledger and transactional outbox, initially on SQLite, then migrated to PostgreSQL (`PostgresTaskLedger`);
- local worker, initially polling the outbox directly, then redesigned around a Redis Streams consumer group with a dedicated `RedisOutboxDispatcher`;
- task state transitions;
- replay/cancel/dead-letter behavior.

Reason:

- The spec requires durable, auditable, retryable production work rather than direct one-off scraping calls, with PostgreSQL as durable authority and Redis Streams as reconstructable delivery infrastructure.

### 4. Added Raw Evidence and Canonical Storage

Implemented:

- raw JSON evidence stored before parser output;
- raw evidence refs carried through results;
- canonical tweet storage;
- engagement observations;
- reprocessing from raw evidence.

Reason:

- The spec explicitly says raw evidence must be stored before normalization so parser bugs can be corrected without recollecting from X.

### 5. Added Session, Release, and Telemetry Operations

Implemented:

- session metadata and leases;
- session health transitions;
- release health;
- release risk;
- telemetry attempts;
- runtime error classification.

Reason:

- The spec separates account/session health, release health, protocol failures, and production retries.

### 6. Added Operator Controls and Support Packages

Implemented:

- replay;
- cancel;
- reprocess;
- investigate;
- failed-task export;
- support export listing/view/download/retention.

Reason:

- The spec requires dead-letter records to preserve diagnostic metadata and replay to be explicit, selective, auditable, and lineage-preserving.

### 7. Added Frontend Console

Implemented a real frontend, not mock data:

- acquisition;
- metrics;
- sessions;
- task actions;
- support exports;
- startup readiness;
- output rendering.

Reason:

- The project needed a presentable operator surface that shows real system state and real output.

### 8. Added Deployment Readiness Tooling

Implemented:

- migrations;
- startup check;
- preflight;
- smoke;
- health report;
- supervisor check;
- logging;
- runbook;
- CI.

Reason:

- The final spec's definition of done includes operations, deployment, retention, safe logs, and observability. The project needed credible verification, not just code.

## Current Spec Coverage Summary

| FINAL_PRODUCT_SPEC area | Current status |
| --- | --- |
| Capability-driven API | Partial, implemented for `SEARCH_TWEETS` |
| Capability planner | Partial, implemented for current release/capability |
| Protocol runtime | Partial foundation |
| Approved protocol release manifest | Present for current search path |
| Raw evidence before parsing | Implemented |
| One-attempt runtime | Implemented |
| Durable task lifecycle | Implemented, PostgreSQL-backed (single-node local) |
| Transactional outbox | Implemented, PostgreSQL-backed |
| Redis Streams delivery | Implemented, single-node local (consumer group, XACK, XAUTOCLAIM reclaim) |
| PostgreSQL durable authority | Implemented, single-node local (Docker Compose, not managed/clustered/HA) |
| Worker leases/fencing | Implemented (task identity + delivery generation + lease token, fenced via `RETURNING`-based Postgres writes) |
| Production retries | Implemented locally (backoff scheduling, retry disposition classification) |
| Dead-letter/replay | Implemented locally |
| Session health and leases | Implemented locally |
| Secret backend | Not implemented; env references only |
| Network allocation plane | Partial; validated route metadata, worker filtering, route health, and remediation guidance |
| Canonical tweet and engagement data | Implemented |
| Broader canonical model | Not implemented |
| Reprocessing from raw evidence | Implemented |
| Protocol telemetry | Implemented locally |
| Release risk/quarantine | Implemented locally |
| Release rollout/rollback lifecycle | Partial; manual health controls only |
| Monitoring subscriptions | Not implemented |
| Frontend operator console | Implemented for current slice |
| Health report/support exports | Implemented |
| Deployment runbook/startup/preflight/supervisor | Implemented |
| Scale/chaos/soak certification | Not implemented |

## What Should Not Be Claimed Yet

Do not call the current repository the complete final product.

Do not claim:

- managed/clustered/HA PostgreSQL or Redis (this is a single-node local Docker Compose instance, not production infrastructure certification);
- distributed worker recovery validated at production scale (the consumer-group/XAUTOCLAIM reclaim path is verified functionally, including a genuine single-crash scenario plus an in-process load/soak/multi-consumer crash-recovery test suite -- 150 concurrent deliveries across 4 workers with zero loss, simultaneous stale-delivery reclaim from 3 crashed consumers, and 20 repeated dispatch/process cycles leaving no backlog -- but not tested against real OS process kills, network partitions, or a sustained multi-hour soak at scale);
- full protocol runtime validation lifecycle;
- all capability families;
- complete account/secret/network subsystem;
- complete analytics/monitoring platform;
- scale/chaos/soak certification;
- final production readiness by the spec's definition.

## Practical Current Claim

The accurate claim is:

> This repository is a production-oriented local vertical slice of the final X protocol ingestion platform, centered on `SEARCH_TWEETS`. Local Postgres and Redis run via Docker Compose; the application itself (web, worker, dispatcher) is plain, uncontainerized Python. It has a PostgreSQL-backed durable task ledger and transactional outbox, Redis-Streams-based delivery with consumer-group fencing and crash recovery, raw evidence, canonical tweet/engagement storage, session/release/error operations, support exports, outbox recovery controls, parser validation fingerprints and saved validation reports plus persisted first-class recipe validation records, secret-provider abstraction with file-backed deployment support, session registry import, per-session credential resolution, startup readiness checks (including Postgres/Redis reachability), a real frontend, deployment runbook, and passing CI (Windows matrix plus a Postgres/Redis-backed Ubuntu job). It is ready to demonstrate and continue hardening, but not yet complete against the final spec.

## Next Recommended Work

1. Decide whether to invest next in:
   - hardening this single-node Postgres/Redis setup (connection pool tuning, `LISTEN`/`NOTIFY` for lower dispatch latency, structured migration tooling beyond the hand-rolled runner), or
   - moving toward managed/clustered Postgres and Redis (replication, Sentinel/Cluster) for genuine production deployment.
2. Add more capabilities only after the `SEARCH_TWEETS` vertical slice has validation tightened.
3. `run_supervisor_check.py`/health reporting now surface Redis consumer-group lag and pending-entry-count metrics alongside Postgres outbox lag, and the delivery path now has an in-process load/soak/crash-recovery test suite (`tests/test_delivery_load.py`, opt-in via `XINGESTION_RUN_LOAD_TESTS=1`, run in the Postgres/Redis CI job). Remaining gap before calling it production-certified: real OS-level process-kill chaos testing and a sustained multi-hour soak at production scale.
