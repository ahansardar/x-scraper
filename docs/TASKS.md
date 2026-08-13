# Implementation Tasks

This is the living checklist for the remaining product work. Completed items are marked with a checked box and strikethrough text so the file shows both status and history.

## Production Release Control

- [x] ~~Pin an approved `ProtocolReleaseManifest` in the production execution path.~~
- [ ] Persist recipe-level validation records with `release_id`, `recipe_revision_id`, `composition_hash`, and runtime version.
- [x] ~~Reject production execution when the pinned release is not approved.~~
- [x] ~~Write redacted release-promotion audit packages for checks, blocked approvals, normal approvals, and forced approvals.~~
- [ ] Persist browser-capture/direct-replay comparison results as first-class release validation records instead of report artifacts only.

## SEARCH_TWEETS Vertical Slice

- [x] ~~Integrate `SEARCH_TWEETS` pagination validation into the production worker path.~~
- [ ] Add explicit cursor-loop evidence to the investigation package when pagination fails.
- [ ] Expand search request inputs to cover the remaining stable contract fields from the product spec.
- [ ] Validate the full `SEARCH_TWEETS` acquisition recipe as a single release-bound unit.

## Durable Execution and Delivery

- [x] ~~Migrate the durable task ledger and transactional outbox from SQLite to PostgreSQL.~~
- [x] ~~Deliver committed outbox rows through Redis Streams with a dedicated dispatcher process.~~
- [x] ~~Consume Redis deliveries through a worker consumer group with fenced Postgres leases and stale pending-entry reclaim.~~
- [x] ~~Add explicit Redis consumer-group lag and pending-entry-count metrics to health reports and supervisor checks.~~
- [ ] Add load, soak, and crash-recovery tests for dispatcher/worker delivery before calling the path production-certified.
- [ ] Decide whether the next hardening step is single-node tuning or managed/clustered Postgres and Redis.

## Runtime and Drift

- [ ] Surface protocol drift reports when the approved recipe starts failing in production.
- [ ] Add recipe-compatibility checks so a parser or operation change forces a fresh validation run.
- [ ] Promote current raw-evidence validation to record the validated recipe composition hash.

## Production Hardening

- [ ] Drain and reconcile any stale outbox backlog before widening rollout.
- [ ] Expand monitoring and release-risk handling around the approved search route.
- [ ] Add connection-pool tuning and lower-latency dispatch wakeups, such as Postgres `LISTEN`/`NOTIFY`, if staying on the single-node local infrastructure path.
- [ ] Replace the hand-rolled Postgres migration runner with structured migration tooling before larger schema growth.
- [ ] Add the next capability vertical slice after `SEARCH_TWEETS` is fully release-governed.
