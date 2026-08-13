# Implementation Tasks

This is the living checklist for the remaining product work. Completed items are marked with a checked box and strikethrough text so the file shows both status and history.

## Production Release Control

- [x] ~~Pin an approved `ProtocolReleaseManifest` in the production execution path.~~
- [x] ~~Persist recipe-level validation records with `release_id`, `recipe_revision_id`, `composition_hash`, and runtime version.~~
- [x] ~~Reject production execution when the pinned release is not approved.~~
- [x] ~~Write redacted release-promotion audit packages for checks, blocked approvals, normal approvals, and forced approvals.~~
- [x] ~~Persist browser-capture/direct-replay comparison results as first-class release validation records instead of report artifacts only.~~

## SEARCH_TWEETS Vertical Slice

- [x] ~~Integrate `SEARCH_TWEETS` pagination validation into the production worker path.~~
- [x] ~~Add explicit cursor-loop evidence to the investigation package when pagination fails.~~
- [x] ~~Expand search request inputs to cover the remaining stable contract fields from the product spec.~~ (`FINAL_PRODUCT_SPEC.md`'s SEARCH_TWEETS Inputs list is exactly `query`, `product`, `cursor`, `page_size` -- `SearchTweetsInput` already has all four; there is no unimplemented spec-named field. The pinned GraphQL operation also has no separate variable slots for filters like language/date-range/result-type -- those are only expressible via X search operators embedded in `query` directly, e.g. `"india lang:en since:2026-01-01"`, which already works today.)
- [x] ~~Validate the full `SEARCH_TWEETS` acquisition recipe as a single release-bound unit.~~

## Durable Execution and Delivery

- [x] ~~Migrate the durable task ledger and transactional outbox from SQLite to PostgreSQL.~~
- [x] ~~Deliver committed outbox rows through Redis Streams with a dedicated dispatcher process.~~
- [x] ~~Consume Redis deliveries through a worker consumer group with fenced Postgres leases and stale pending-entry reclaim.~~
- [x] ~~Add explicit Redis consumer-group lag and pending-entry-count metrics to health reports and supervisor checks.~~
- [x] ~~Add load, soak, and crash-recovery tests for dispatcher/worker delivery before calling the path production-certified.~~
- [ ] Decide whether the next hardening step is single-node tuning or managed/clustered Postgres and Redis.

## Runtime and Drift

- [x] ~~Surface protocol drift reports when the approved recipe starts failing in production.~~
- [x] ~~Add recipe-compatibility checks so a parser or operation change forces a fresh validation run.~~
- [x] ~~Promote current raw-evidence validation to record the validated recipe composition hash.~~

## Production Hardening

- [ ] Drain and reconcile any stale outbox backlog before widening rollout.
- [ ] Expand monitoring and release-risk handling around the approved search route.
- [ ] Add connection-pool tuning and lower-latency dispatch wakeups, such as Postgres `LISTEN`/`NOTIFY`, if staying on the single-node local infrastructure path.
- [ ] Replace the hand-rolled Postgres migration runner with structured migration tooling before larger schema growth.
- [ ] Add the next capability vertical slice after `SEARCH_TWEETS` is fully release-governed.

## Spec-Flagged Gaps Not Yet Started (`FINAL_PRODUCT_SPEC.md`)

Found via a full read of `FINAL_PRODUCT_SPEC.md` against the current implementation (2026-08-13). These are larger, un-started subsystems the spec calls for that never made it onto this checklist -- tracked here so they aren't lost, deliberately not started while the smaller "Production Hardening" items above are still open.

- [ ] Monitoring subscriptions (spec §28): persistent subscriptions with a scheduler, acquisition coalescing, watermarks, gap detection, bounded backfill, outage catch-up, priority/backpressure. Currently zero implementation -- every acquisition today is a one-shot task, not a standing subscription.
- [ ] A genuinely stable northbound API (spec §30): today's `/api/*` surface is the trusted operator console (Postgres/Redis/session internals visible to the operator), not the external product-facing capability API the spec describes (`POST /capabilities/search-tweets`, `POST /jobs`, `GET /jobs/{id}`, `GET /results/{id}`, `POST /monitors`).
- [ ] Broader canonical data model (spec §19): canonical storage today is tweets + engagement observations only. Spec calls for `User`, `List`, `Community`, `RelationshipEdge`, `ProfileObservation` as first-class canonical entities with correct object-identity and time-semantics rules (`source_created_at`/`captured_at`/`first_seen_at`/`last_seen_at`/`source_updated_at`/`normalized_at` kept separate).
- [ ] Real release rollout/rollback lifecycle (spec §26): today release health is manually toggled (ACTIVE/DEGRADED/QUARANTINED/etc.) with no automated canary stage or automated failover to a known-good approved release. Spec describes `CANDIDATE -> OFFLINE_VALIDATED -> LIVE_VALIDATED -> RELEASE_CANDIDATE -> APPROVED -> CANARY -> PRODUCTION`, with automated `QUARANTINED -> APPROVED` rollback to a known-good release.
