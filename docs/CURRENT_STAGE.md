# Current Stage Against FINAL_PRODUCT_SPEC

Date: 2026-08-11

This document records where `F:\x-scraper` currently stands relative to `FINAL_PRODUCT_SPEC.md`, and how the implementation reached this stage.

## Current Label

The project is currently a production-oriented local vertical slice for `SEARCH_TWEETS`.

It is not yet the complete final product described in `FINAL_PRODUCT_SPEC.md`. The final spec describes a two-system platform split between:

- `X-rev-os`: protocol research, validation, request construction, parsing, pagination, and approved protocol releases.
- `XINGESTIONV2`: production ingestion, durable orchestration, retries, accounts/sessions/network allocation, canonical data, APIs, monitoring, and operations.

This repository now contains a working local slice of both ideas:

- `src/xrev/` contains protocol/runtime foundations.
- `src/xingestion/` contains the production ingestion control plane, worker, storage, APIs, frontend, and operations tooling.
- `playground/` contains the older experimental GraphQL scripts and research artifacts.

## Current Verified State

Latest verified pushed state:

- Latest commit at the time of this document: `e0d14f9 Record startup readiness verification`.
- GitHub Actions CI passed on Windows for Python 3.11 and 3.12.
- Local startup directory readiness passes.
- The working implementation uses no Docker.
- Default local storage is under `F:\x-scraper\data`.

Important runtime locations:

- SQLite task/canonical/session state: `F:\x-scraper\data\tasks.sqlite3`
- Raw evidence: `F:\x-scraper\data\raw_evidence`
- Logs: `F:\x-scraper\data\logs`
- Health reports: `F:\x-scraper\data\reports`
- Support exports: `F:\x-scraper\data\support_exports`

Known current operational signal:

- `run_supervisor_check.py --base-url http://127.0.0.1:8000` confirmed startup readiness, but reported existing queue lag: `oldest_unpublished_lag_seconds` exceeded the default threshold.
- The next operational step should address old unpublished outbox events with queue drain/redrive guidance or operator controls.

## What Is Implemented

### Spec-Aligned Capability Boundary

Implemented:

- Stable capability request shape for `SEARCH_TWEETS`.
- Generic `POST /api/capability-tasks`.
- UI shortcut `POST /api/search-tweets`.
- Capability planner boundary.
- Protocol release manifest pinned from `protocol_releases/`.
- Backpressure before task creation through `XINGESTION_MAX_ACTIVE_TASKS_PER_CAPABILITY`.

Spec relevance:

- Matches the spec principle that production clients request capabilities, not raw X endpoint details.
- Current scope is one capability, not the full capability family listed in the spec.

### X-rev Runtime Foundation

Implemented:

- SearchTweets request/runtime model.
- One-attempt transport boundary.
- Raw evidence sink protocol and file-backed raw evidence sink.
- Parser for protocol-normalized tweet records.
- Pagination cursor extraction for the current search path.
- Protocol release manifest and revision-style structures.

Spec relevance:

- Aligns with the spec's raw-first, one-attempt, protocol-owned request/parser boundary.
- Not yet a complete X-rev-os protocol authority with full research workbench, historical registry, complete validation lifecycle, and broad drift intelligence.

### Production Control Plane

Implemented locally:

- Durable task ledger using SQLite.
- Task states including created, enqueued, running, retry scheduled, done, dead letter, cancelled.
- Transactional outbox table.
- Local worker that dispatches from outbox.
- Idempotent task creation.
- Replay lineage for dead-letter tasks.
- Cancel, replay, reprocess, investigate, and export controls.

Spec relevance:

- Implements the shape of the spec's durable task lifecycle and outbox model.
- The final spec calls for PostgreSQL as durable authority and Redis Streams as delivery infrastructure. This repository currently uses SQLite plus a local outbox worker, so it is a local production candidate, not the final distributed control plane.

### Sessions, Auth, and Network

Implemented:

- Session metadata stored without raw secret values.
- Default local session references `.env` values through a credential reference.
- Session health states and health transitions.
- Session leases with expiry.
- Session restore/disable operator controls.
- Rate/auth-related session health behavior.
- Safe session attempt visibility: attempts, successes, failures, last attempt, last success, last error.

Spec relevance:

- Matches the spec's separation of session metadata, credential references, health, and leases.
- Not yet a full production account, secret backend, and network allocation plane.

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

- No-Docker local deployment path.
- `.env`-driven configuration.
- Persistent data directory override via `XINGESTION_DATA_DIR`.
- Migrations.
- Startup check command: `run_startup_check.py`.
- Preflight command: `run_preflight.py`.
- Smoke command: `run_smoke.py`.
- Supervisor check command: `run_supervisor_check.py`.
- Health report export: `run_health_report.py`.
- Rotating logs.
- Retention controls.
- GitHub Actions CI on Python 3.11 and 3.12.

Spec relevance:

- Covers a meaningful part of the spec's operations/deployment hardening requirement.
- Still missing scale, chaos, soak, capacity testing, SLOs, and production infrastructure certification.

## How We Got Here

The current stage was built incrementally rather than as one large unverified rewrite.

### 1. Moved Historical Work to Playground

The older GraphQL scripts and exploratory artifacts were moved under `playground/`.

Reason:

- The final spec treats `x-scraper` history as research/prototype origin.
- New production code needed a cleaner split between protocol runtime and ingestion control plane.

### 2. Built Protocol Runtime Foundations

Implemented under `src/xrev/`:

- protocol release/revision models;
- SearchTweets request builder/runtime concepts;
- one-attempt transport boundary;
- parser and pagination extraction;
- raw evidence sink interface and file implementation;
- typed protocol errors.

Reason:

- The spec requires X-specific request construction, parsing, and pagination to live behind a protocol runtime boundary rather than being spread through production code.

### 3. Built XINGESTION Task Control Plane

Implemented under `src/xingestion/`:

- capability requests;
- planner;
- SQLite task ledger;
- transactional outbox;
- local worker;
- task state transitions;
- replay/cancel/dead-letter behavior.

Reason:

- The spec requires durable, auditable, retryable production work rather than direct one-off scraping calls.

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
| X-rev protocol runtime | Partial foundation |
| Approved protocol release manifest | Present for current search path |
| Raw evidence before parsing | Implemented |
| One-attempt runtime | Implemented |
| Durable task lifecycle | Implemented locally with SQLite |
| Transactional outbox | Implemented locally |
| Redis Streams delivery | Not implemented |
| PostgreSQL durable authority | Not implemented |
| Worker leases/fencing | Partial local implementation |
| Production retries | Partial local implementation |
| Dead-letter/replay | Implemented locally |
| Session health and leases | Implemented locally |
| Secret backend | Not implemented; env references only |
| Network allocation plane | Not implemented; direct route metadata only |
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

- full PostgreSQL/Redis production architecture;
- distributed worker recovery through Redis consumer groups;
- full X-rev validation lifecycle;
- all capability families;
- complete account/secret/network subsystem;
- complete analytics/monitoring platform;
- scale/chaos/soak certification;
- final production readiness by the spec's definition.

## Practical Current Claim

The accurate claim is:

> This repository is a no-Docker, production-oriented local vertical slice of the final X protocol ingestion platform, centered on `SEARCH_TWEETS`. It has durable local tasks, raw evidence, canonical tweet/engagement storage, session/release/error operations, support exports, outbox recovery controls, parser validation fingerprints and saved validation reports, secret-provider abstraction with file-backed deployment support, startup readiness checks, a real frontend, deployment runbook, and passing CI. It is ready to demonstrate and continue hardening, but not yet complete against the final spec.

## Next Recommended Work

1. Decide whether the next infrastructure step is:
   - continue no-Docker local SQLite hardening, or
   - begin migration toward PostgreSQL and Redis Streams as specified.
2. Add more capabilities only after the `SEARCH_TWEETS` vertical slice has validation tightened.
3. Move from local SQLite/outbox to PostgreSQL plus Redis Streams when distributed deployment becomes the next priority.
