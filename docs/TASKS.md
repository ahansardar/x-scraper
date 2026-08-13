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
- [x] ~~Decide whether the next hardening step is single-node tuning or managed/clustered Postgres and Redis.~~

## Runtime and Drift

- [x] ~~Surface protocol drift reports when the approved recipe starts failing in production.~~
- [x] ~~Add recipe-compatibility checks so a parser or operation change forces a fresh validation run.~~
- [x] ~~Promote current raw-evidence validation to record the validated recipe composition hash.~~

## Production Hardening

- [x] ~~Drain and reconcile any stale outbox backlog before widening rollout.~~
- [x] ~~Expand monitoring and release-risk handling around the approved search route.~~
- [x] ~~Add connection-pool tuning and lower-latency dispatch wakeups, such as Postgres `LISTEN`/`NOTIFY`, if staying on the single-node local infrastructure path.~~
- [ ] Replace the hand-rolled Postgres migration runner with structured migration tooling before larger schema growth.
- [ ] Add the next capability vertical slice after `SEARCH_TWEETS` is fully release-governed.

## Spec-Flagged Gaps Not Yet Started (`FINAL_PRODUCT_SPEC.md`)

Found via a full section-by-section read of `FINAL_PRODUCT_SPEC.md` against the current implementation (2026-08-13, expanded from an initial pass on the same date). Tracked here so they aren't lost, deliberately not started while the smaller "Production Hardening" items above are still open. Each cites the exact spec section so the gap can be re-verified against the spec text directly rather than trusted from this summary.

### New subsystems (largest gaps -- effectively unstarted)

- [ ] Monitoring subscriptions (spec §28): persistent subscriptions with a scheduler, acquisition coalescing, watermarks, gap detection, bounded backfill, outage catch-up, priority/backpressure. Currently zero implementation -- every acquisition today is a one-shot task, not a standing subscription.
- [ ] A genuinely stable northbound API (spec §30): today's `/api/*` surface is the trusted operator console (Postgres/Redis/session internals visible to the operator), not the external product-facing capability API the spec describes (`POST /capabilities/search-tweets`, `POST /jobs`, `GET /jobs/{id}`, `GET /results/{id}`, `POST /monitors`).
- [ ] Broader canonical data model (spec §19): canonical storage today is tweets + engagement observations only. Spec calls for `User`, `List`, `Community`, `RelationshipEdge`, `ProfileObservation` as first-class canonical entities with correct object-identity and time-semantics rules (`source_created_at`/`captured_at`/`first_seen_at`/`last_seen_at`/`source_updated_at`/`normalized_at` kept separate).
- [ ] Real release rollout/rollback lifecycle (spec §26): today release health is manually toggled (ACTIVE/DEGRADED/QUARANTINED/etc.) with no automated canary stage or automated failover to a known-good approved release. Spec describes `CANDIDATE -> OFFLINE_VALIDATED -> LIVE_VALIDATED -> RELEASE_CANDIDATE -> APPROVED -> CANARY -> PRODUCTION`, with automated `QUARANTINED -> APPROVED` rollback to a known-good release.
- [ ] Downstream analytics/alerts/briefs, decoupled from acquisition (spec §29): none of these exist yet, so there is nothing to decouple today -- tracked so that when they're added, they're built as downstream consumers of canonical data from the start (per the spec's explicit architecture) rather than folded into the acquisition path.

### Narrower, concrete gaps found on this deeper pass

- [ ] Typed protocol error taxonomy is far smaller than the spec's (spec §21): the spec lists 24 typed error classes; `src/xingestion/errors.py`'s `ERROR_PROFILES` currently classifies 9 (`AUTH_OR_SESSION_REJECTED`, `OPERATION_NOT_FOUND`, `PROTOCOL_RELEASE_BLOCKED`, `RATE_LIMITED`, `SESSION_UNAVAILABLE`, `TASK_NOT_FOUND`, `TRANSPORT_ERROR`, `UNEXPECTED_HTTP_STATUS`, `UPSTREAM_SERVER_ERROR`), plus the pagination/parser classes raised elsewhere without a profile entry (falling back to a generic classification). Missing entirely: `SESSION_INVALID`, `SESSION_CHALLENGED`, `AUTH_ATTACHMENT_INVALID`, `TRANSPORT_TIMEOUT`, `NETWORK_FAILURE`, `HTTP_SERVER_FAILURE`, `TEMPORARY_UNAVAILABLE`, `OPERATION_CONTRACT_CHANGED`, `FEATURE_OR_CONFIG_CHANGED`, `SHARED_TRANSACTION_PROFILE_CHANGED`, `CLIENT_BUILD_CHANGED`, `RESPONSE_SCHEMA_VARIANT`, `RAW_EVIDENCE_PERSISTENCE_FAILED`, `ACCESS_NOT_AUTHORIZED`, `OBJECT_NOT_FOUND`, `UNSUPPORTED_CAPABILITY`, `BUNDLE_RUNTIME_INCOMPATIBLE`, `UNKNOWN_PROTOCOL_FAILURE`.
- [ ] No automated sanitized-fixture pipeline (spec §32): the spec describes `Raw Capture -> Automated Sanitization -> Secret Scan -> Human Verification -> VERIFIED_SANITIZED -> Committed Regression Fixture`. Nothing in `src/xingestion/` implements automated sanitization, secret scanning, or a verification-state marker -- committed fixtures under `tests/fixtures/search_tweets/` are manually curated with no tooling enforcing the pipeline.
- [ ] No distinct `Account` entity separate from `SessionArtifact` (spec §10.1-10.2): the spec models `Account -> CredentialRef` and `Account -> SessionArtifact` as separate concepts (identity vs. usable session material). Today's `SessionRecord` conflates them -- `account_label` is just a string field on the session row, with no independent account/credential-reference model an operator could query across multiple sessions for the same account.
- [ ] Several spec-listed observability metrics are not tracked (spec §33): missing explicitly -- `session_concurrency` (as a distinct metric from session count/health), a live `schema_fingerprint` metric outside of validation-report runs (fingerprints exist in `protocol_validation.py` but aren't surfaced as an ongoing production signal), `normalization_lag`, and `monitor_lag` (N/A until monitoring subscriptions exist). Latency is recorded per-attempt (`duration_ms`) but not aggregated/exposed as p50/p95 anywhere.
- [ ] X-rev protocol validation lifecycle stages 4-8 are not built (spec §24): stage 3 (parser + pagination + full recipe validation) is done for `SEARCH_TWEETS` as of this session. Stages 4 (broader Workbench/CLI beyond `run_protocol_validation.py`/`run_releases.py`), 5 (historical protocol registry/diff intelligence), 6 (more capabilities), 7 (mature drift intelligence beyond the current recency-windowed report), and 8 (bounded candidate/self-healing lifecycle) are not started.
- [ ] Only one of eleven spec-listed capabilities exists (spec §5): `SEARCH_TWEETS` is implemented; `TWEET_BY_ID`, `TWEET_REPLIES`, `TWEET_QUOTES`, `USER_LOOKUP`, `USER_TIMELINE`, `FOLLOWERS`, `FOLLOWING`, `LIST_TIMELINE`, `COMMUNITY_TIMELINE`, `MONITOR_QUERY`, `MONITOR_USER` are not. (This is the same gap as "Add the next capability vertical slice" above, made concrete against the spec's actual list.)
