# Deployment Runbook

This runbook covers local Postgres and Redis infrastructure started via Docker Compose, with the application itself (web, worker, dispatcher) running as plain OS processes -- not containerized. Sessions, canonical tweets/observations, releases, telemetry, and reprocess jobs stay on SQLite; the durable task ledger and transactional outbox live in PostgreSQL, delivered to workers over Redis Streams.

## Required Environment

Create `.env` beside `run_app.py`.

```env
X_AUTH_TOKEN=
X_CT0=
X_BEARER=
XINGESTION_DATA_DIR=F:\x-scraper-data
XINGESTION_HOST=127.0.0.1
XINGESTION_PORT=8000
XINGESTION_RETENTION_DAYS=30
XINGESTION_SESSION_ID=local-env-session
XINGESTION_ACCOUNT_LABEL=local-env
XINGESTION_CREDENTIAL_REF=env:X_AUTH_TOKEN,X_CT0,X_BEARER
XINGESTION_SECRET_PROVIDER=env
XINGESTION_SECRET_DIR=
XINGESTION_SESSION_REGISTRY=
XINGESTION_NETWORK_CONTEXT=direct
XINGESTION_WORKER_NETWORK_CONTEXT=
XINGESTION_REQUIRE_MIGRATIONS=true
XINGESTION_MAX_ACTIVE_TASKS_PER_CAPABILITY=100
XINGESTION_LOG_DIR=
XINGESTION_LOG_LEVEL=INFO
XINGESTION_LOG_MAX_BYTES=5242880
XINGESTION_LOG_BACKUP_COUNT=5

# Task ledger + outbox dispatch (PostgreSQL + Redis Streams).
# Local defaults match docker-compose.yml; port 55432 avoids clashing with
# any locally-installed Postgres service.
XINGESTION_POSTGRES_DSN=postgresql://xingestion:xingestion@127.0.0.1:55432/xingestion
XINGESTION_POSTGRES_POOL_MIN=1
XINGESTION_POSTGRES_POOL_MAX=10
XINGESTION_REDIS_URL=redis://127.0.0.1:6379/0
XINGESTION_REDIS_STREAM=xingestion:capability-tasks
XINGESTION_REDIS_CONSUMER_GROUP=capability-workers
XINGESTION_REDIS_CONSUMER_NAME=
XINGESTION_DISPATCHER_POLL_SECONDS=1.0
XINGESTION_WORKER_LEASE_HEARTBEAT_SECONDS=100
XINGESTION_REDIS_CLAIM_MIN_IDLE_MS=300000
```

Use a persistent disk for `XINGESTION_DATA_DIR`. Do not use the build checkout as production storage.

For deployment-mounted secrets, set:

```env
XINGESTION_SECRET_PROVIDER=file
XINGESTION_SECRET_DIR=F:\x-scraper-secrets
XINGESTION_CREDENTIAL_REF=file:session-a
```

Then create `F:\x-scraper-secrets\session-a.json` outside git:

```json
{
  "auth_token": "...",
  "ct0": "...",
  "bearer_token": "..."
}
```

Preflight exposes only provider status and missing field names. It does not print token values.

For multiple authorized sessions, create a registry file outside git:

```json
{
  "sessions": [
    {
      "session_id": "session-a",
      "account_label": "authorized-account-a",
      "credential_ref": "file:session-a",
      "network_context": "proxy:pool-a:iad",
      "health": "HEALTHY"
    },
    {
      "session_id": "session-b",
      "account_label": "authorized-account-b",
      "credential_ref": "file:session-b",
      "network_context": "direct:sfo",
      "health": "DISABLED"
    }
  ]
}
```

`network_context` is parsed as `kind[:route][:region]`; supported kinds are `direct`, `proxy`, and `vpn`. Set `XINGESTION_WORKER_NETWORK_CONTEXT` on a deployed worker to bind it to a route or pool, such as `proxy:pool-a` or `direct:sfo`. The worker will only lease sessions that match the requested kind plus any supplied route/region.

Point the app at it:

```env
XINGESTION_SESSION_REGISTRY=F:\x-scraper-secrets\sessions.json
```

Import or inspect the session inventory:

```powershell
python .\run_sessions.py --import-registry F:\x-scraper-secrets\sessions.json --json
python .\run_sessions.py --json
```

The web console can run the same configured import through:

```text
POST /api/sessions/import
```

The `POST` route is available from the trusted console without an admin-token header. Import output shows session IDs, account labels, network contexts, health, and reference schemes; it does not return `credential_ref` values.

## Start Infrastructure

Bring up local Postgres and Redis via Docker Compose (the only containerized pieces -- the application itself is never containerized):

```powershell
docker compose up -d
docker compose ps
```

Wait until both services report `healthy` before continuing.

## Start

For local development, the launcher starts the whole stack in one command:

```powershell
.\run_all.ps1
```

It starts Docker Compose infrastructure, waits for Postgres/Redis health, applies Postgres and SQLite migrations, starts the web frontend/backend, dispatcher, and worker, writes logs under `data\run_all\logs`, and runs live preflight. Stop the Python processes with:

```powershell
.\run_all.ps1 -Stop
```

The manual production-equivalent process layout is:

Apply migrations to both stores:

```powershell
python .\run_postgres_migrations.py
python .\run_migrations.py
python .\run_startup_check.py
python .\run_preflight.py
python .\run_health_report.py
```

Terminal 1:

```powershell
python .\run_app.py --host 0.0.0.0 --port 8000
```

Terminal 2:

```powershell
python .\run_worker.py
```

Terminal 3:

```powershell
python .\run_dispatcher.py
```

The dispatcher publishes committed-but-undelivered outbox rows from Postgres to the Redis stream; the worker consumes that stream via a consumer group. Both are required, always-on processes alongside the web app -- see [process_supervision.md](process_supervision.md) for supervising all three.

The dispatcher's primary wake path is a Postgres `LISTEN`/`NOTIFY` trigger (`notify_outbox_event_created`, migration `002_outbox_notify_trigger.sql`) on the `xingestion_outbox_events` channel: every committed `outbox_events` insert immediately wakes the dispatcher, which then drains every currently pending row in one cycle before going back to listening. If the notify listener can't connect (logged as a warning), the dispatcher falls back to the original fixed-interval poll loop (`XINGESTION_DISPATCHER_POLL_SECONDS`) automatically -- no separate flag needed.

After the web process is listening, verify the deployed API shape:

```powershell
python .\run_startup_check.py
python .\run_preflight.py --base-url http://127.0.0.1:8000
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000
python .\run_health_report.py --base-url http://127.0.0.1:8000
```

## Health Checks

```text
GET /api/health
GET /api/startup
GET /api/storage
GET /api/metrics
GET /api/migrations
GET /api/telemetry
GET /api/network-health
GET /api/sessions
GET /api/releases
GET /api/releases/current
GET /api/releases/current/risk
```

For supervised hosts, run:

```powershell
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes --require-external-data-dir
```

This fails if the API is not returning JSON, startup directories are not writable, migrations are pending, storage is still inside the checkout, no healthy session exists, a required network route has no healthy matching session, a network route exceeds the configured failure-rate threshold after enough attempts, the release is blocked, outbox lag/depth exceeds thresholds, the Redis consumer-group pending-entry count or oldest-pending idle time exceeds thresholds (`--max-redis-pending-entries`, default 100; `--max-redis-pending-idle-seconds`, default 300; WARNs instead of FAILs if the consumer group has not been created yet), or the expected web/worker command lines are missing.

For route-bound workers, pass the same route the worker uses:

```powershell
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes --required-network-context proxy:pool-a --max-network-failure-rate 0.8 --min-network-attempts 5
```

`GET /api/releases/current/risk`, `GET /api/network-health`, health reports, and the frontend Network Health panel all keep route remediation separate from release quarantine. If the action is `NETWORK_REMEDIATION_RECOMMENDED`, rotate or pause the affected session/proxy/VPN route first; quarantine the release only when release-level protocol drift signals such as repeated operation or parser failures are present.

The app stores:

- task ledger and transactional outbox: PostgreSQL (`XINGESTION_POSTGRES_DSN`)
- outbox delivery: Redis Streams (`XINGESTION_REDIS_URL`, stream `XINGESTION_REDIS_STREAM`) -- reconstructable from Postgres; never the authority
- sessions, releases, telemetry, reprocess jobs: `XINGESTION_DATA_DIR\tasks.sqlite3`
- raw evidence: `XINGESTION_DATA_DIR\raw_evidence`
- canonical tweets and observations: `tasks.sqlite3`
- health report exports: `XINGESTION_DATA_DIR\reports\health-report-*.json`
- rotating logs: `XINGESTION_DATA_DIR\logs`

Session records expose `health`, lease metadata, `network_context`, parsed network policy, `cooldown_until`, attempt counters, last attempt/success times, and the latest error class/message. HTTP 429 protocol responses cool down only the leased session, so other healthy sessions can continue processing while the limited account waits. Once the cooldown expires, a successful retry restores that session to `HEALTHY`.

## Submit Work

```http
POST /api/capability-tasks
Content-Type: application/json

{
  "capability_id": "SEARCH_TWEETS",
  "contract_version": 1,
  "payload": {
    "query": "india lang:en",
    "product": "Top",
    "page_size": 20
  },
  "idempotency_key": "client-request-001"
}
```

`TWEET_BY_ID` uses the same route with a `tweet_id` payload (or the `POST /api/tweet-by-id` shortcut, `{"tweet_id": "..."}`). Its recipe binding now carries a real captured `operation_id` (`CANDIDATE`/`OBSERVED` as of 2026-08-14) but is still unapproved -- `validation_freshness` is `NEVER_VALIDATED` because `protocol_validation.py`'s fixture/capture-replay pipeline is still hardcoded to `SEARCH_TWEETS` (see `docs/TASKS.md`). It has no cursor/`max_pages` concept; it always resolves to a single-page plan.

Poll `status_url` until the task is `DONE`, then read `result_url`.

## Operator Controls

Operator `POST` routes are trusted-console routes and do not require an admin-token header.

Cancel pending work:

```text
POST /api/tasks/{task_id}/cancel
```

Replay failed work:

```text
POST /api/tasks/{task_id}/replay
```

Quarantine a suspect protocol release:

```text
POST /api/releases/current/quarantine
```

Reactivate it after investigation:

```text
POST /api/releases/current/activate
```

List and approve staged protocol manifests:

```powershell
python .\run_releases.py --json
python .\run_releases.py current --json
python .\run_releases.py check xrev-search-tweets-2026-08-10-candidate-1 --json
python .\run_releases.py approve xrev-search-tweets-2026-08-10-candidate-1 --reason operator_approved --json
python .\run_releases.py audits --json
python .\run_releases.py audit promotion-...json --json
python .\run_releases.py prune-audits --json
python .\run_releases.py prune-audits --days 30 --apply --json
```

Equivalent trusted-console routes:

```text
GET /api/releases
POST /api/releases/approve
GET /api/releases/audits
GET /api/releases/audits/{name}
GET /api/releases/audits/{name}/download
POST /api/releases/audits/retention
```

Release approval first runs promotion safety checks: manifest presence, release health, binding presence, recipe binding consistency, checked-in fixture validation, and browser-capture/direct-replay comparison when pairs exist. A failed safety report blocks normal approval; use `--force` or `force: true` only for an explicit emergency override. Release approval updates `approved_protocol_release` in SQLite and reloads the live process planner/worker so new tasks use the exact approved manifest. With more than one manifest in `protocol_releases`, startup requires this pointer to be present and resolvable.

`recipe_binding_consistency` validates each binding's recipe as one bound unit rather than components checked in isolation: it builds a real (probe-credentialed) request via `build_search_timeline_request()` from the recipe's `operation`/`auth_profile`/`transaction_profile` together, then checks that `auth_profile.required_material` matches what `WebSessionAuth` actually requires and that every header in `transaction_profile.required_headers` is one the request builder actually sets. This is declarative metadata that nothing else enforces stays in sync with the real request-building code -- previously, a mismatch here would only ever surface as a live 401/rejected request in production, never as a pre-flight check.

Every `run_releases.py check`, normal approval, blocked approval, and force approval writes a redacted `RELEASE_PROMOTION_AUDIT` package under `XINGESTION_DATA_DIR\release_promotions` by default. The package records the release ID, exact manifest path, approval pointer before/after, promotion safety report, force flag, and operator reason without raw X secrets or raw evidence bodies. Detail reads and downloads accept only `promotion-*.json` file names from that directory; they do not accept arbitrary paths. `prune-audits` dry-runs by default and deletes only matched `promotion-*.json` files when `--apply` is provided. The trusted console Promotion Trail uses `XINGESTION_RETENTION_DAYS` for its dry-run and cleanup count.

Review advisory release-risk recommendations:

```text
GET /api/releases/current/risk
```

Review whether the approved recipe is drifting in live production right now:

```text
GET /api/releases/current/drift
```

`release_risk` (above) scores lifetime-cumulative error counts and never resets -- a release with a handful of failures months ago stays flagged forever, and a release that just started failing is diluted by a long healthy history. `protocol_drift` complements it by looking only at the most recent attempts (default window 20) against the *currently* approved recipe: `drifting=true` at `HIGH` severity means `OPERATION_NOT_FOUND` or `PARSER_FAILURE` appeared at all in that window (the approved recipe is failing against live X responses right now); at `MEDIUM` severity it means either the recent failure rate is at or above 40%, or the recipe's live composition has no fresh, passing validation record (see `recipe_validation_freshness` above). It is surfaced in health reports, `/api/metrics`, and as a non-blocking `WARN` (never `FAIL`) in `run_supervisor_check.py` -- deliberately not a hard gate, since a transient recent glitch shouldn't block an otherwise-working deployment.

`search_route_monitoring` (in `/api/metrics`, the health report, and the frontend metrics strip) is a presentation layer over `release_risk` and the network-route recommendations, scoped to one target network context (`XINGESTION_WORKER_NETWORK_CONTEXT`, default `direct`): it picks whichever signal is most actionable for that specific route -- `RELEASE_BLOCKED`/`QUARANTINE_RECOMMENDED` (release-level, `HIGH`), a route-level `NETWORK_REMEDIATION_RECOMMENDED`/`ROTATE_OR_PAUSE_ROUTE` (`MEDIUM`), `NO_ROUTE_DATA` if nothing has been observed yet, or `CONTINUE_MONITORING` if the approved route is healthy. `run_supervisor_check.py`'s `search_route_monitoring` check `FAIL`s on the release-level cases and `WARN`s on the route-level ones.

Restore a fixed session to worker rotation:

```text
POST /api/sessions/{session_id}/restore
```

Disable a session without deleting its metadata:

```text
POST /api/sessions/{session_id}/disable
```

Reprocess stored raw evidence without recollecting:

```text
POST /api/tasks/{task_id}/reprocess
```

Build a protocol drift investigation package:

```text
POST /api/tasks/{task_id}/investigate
```

For a task that failed pagination (`PAGINATION_CURSOR_MISSING`, `PAGINATION_EMPTY_CONTINUATION`, or `PAGINATION_CURSOR_LOOP`), the investigation package's `pagination_chain` field lists every prior page in that task's continuation chain (task ID, page number, and the cursor used to fetch it, oldest first), so the exact cursor sequence leading up to the failure is visible without cross-referencing tasks by hand. The worker itself also now checks a failing page's cursor against every cursor used earlier in the chain, not just the immediately previous one -- a loop back to an older page's cursor is caught as `PAGINATION_CURSOR_LOOP` instead of silently continuing to paginate.

Write a safe failed-task support package from the web API:

```text
POST /api/tasks/{task_id}/export
```

Export a failed-task support package without requiring a running web API:

```powershell
python .\run_failed_task_export.py <task_id>
```

The package is written to `XINGESTION_DATA_DIR\support_exports` by default. It includes runtime error classification, release/session/telemetry context, and raw evidence references, but not raw X secrets or raw evidence bodies. The Needs Attention panel exposes this export for failed tasks and shows the saved path plus redaction metadata.

List and retain generated support exports:

```text
GET /api/support-exports
GET /api/support-exports/{file_name}
GET /api/support-exports/{file_name}/download
POST /api/support-exports/retention
```

The Support Exports panel uses the same endpoints. Detail reads and downloads accept only `failed-task-*.json` file names from `XINGESTION_DATA_DIR\support_exports`; they do not accept arbitrary paths. Downloads return attachment headers. Retention uses `XINGESTION_RETENTION_DAYS` and deletes only `failed-task-*.json` files inside that directory.

List failed and retryable tasks with recommended next actions:

```powershell
python .\run_task_actions.py
python .\run_task_actions.py --json
```

The web console mirrors this in the Needs Attention panel. Parent/operator tooling can read the same JSON at:

```text
GET /api/task-actions
```

Inspect transactional outbox lag and the oldest unpublished events:

```powershell
python .\run_outbox.py --json
```

Process a bounded batch through the same local worker path used in deployment:

```powershell
python .\run_outbox.py --process --limit 5 --json
```

Equivalent web API routes:

```text
GET /api/outbox
POST /api/outbox/process
```

The `POST` route does not require an admin-token header. In normal operation, outbox delivery goes through `run_dispatcher.py` and Redis Streams; this manual route/CLI path still exists as a direct drain and executes `LocalWorker.process_one()` against a pending stream delivery, so release quarantine, session availability, retry scheduling, telemetry, canonical persistence, and continuation queueing all stay active.

Reconcile the Redis stream against Postgres (the durable authority) for entries whose task no longer exists -- this can happen if retention deletes a terminal task before a stalled or backlogged consumer group ever delivers its still-unread stream entry. Dry-run by default:

```powershell
python .\run_outbox.py --reconcile-stream --json
python .\run_outbox.py --reconcile-stream --apply --json
```

```text
POST /api/outbox/reconcile-stream
```

Body `{"limit": 500, "dry_run": true}` (both optional, these are the defaults). An orphaned entry can never be successfully processed -- a worker would immediately drop it as `TASK_NOT_FOUND` -- so deleting it via `XDEL` loses nothing; entries whose task still exists are never touched, regardless of age (that's a dispatch-lag concern, see `redis_queue` stats above, not an orphan).

Validate the pinned `SEARCH_TWEETS` parser before and after protocol changes:

```powershell
python .\run_protocol_validation.py --fixtures-only --json
python .\run_protocol_validation.py --raw-only --json
python .\run_protocol_validation.py --raw-only --write --json
python .\run_protocol_validation.py --compare-captures --json
```

The first command checks committed GraphQL regression fixtures. The second checks local captured payloads under `XINGESTION_DATA_DIR\raw_evidence`. The comparison command replays recent replayable browser captures through the approved release recipe, stores linked `direct_replay` evidence in the same raw evidence directory, and compares parser success plus structural/typename fingerprints. Live timeline tweet counts can change between capture and replay, so counts and engagement coverage are reported as observations instead of hard drift failures. The report includes parsed tweet counts, engagement metric coverage, bottom-cursor presence, and stable fingerprints to compare when X changes the response shape. The web console mirrors the read-only combined view and the replay-writing operator run at:

```text
GET /api/protocol-validation
GET /api/protocol-validation/reports
POST /api/protocol-validation/run
GET /api/releases/validation-records
```

Saved reports are written to `XINGESTION_DATA_DIR\protocol_validation`. The `POST` route does not require an admin-token header and runs direct replays for recent replayable captures before writing the validation response.

Every `POST /api/protocol-validation/run` and every release promotion safety check (`run_releases.py check`/`approve`, `POST /api/releases/approve`) also persists a first-class `recipe_validation_record` row per approved-manifest capability binding: `release_id`, `recipe_revision_id`, `composition_hash`, `runtime_version`, `validation_type` (`FIXTURE` or `CAPTURE_REPLAY`), `ok`, and a summary, in the SQLite task database. `GET /api/releases/validation-records` returns the current release's recent history from this table -- a queryable answer to "was this exact recipe composition ever validated, and did it pass," independent of the JSON report artifacts above.

Bulk reprocess completed tasks for a release:

```text
POST /api/reprocess/jobs
```

Run terminal-task retention cleanup:

```text
POST /api/retention/run
```

Export an operator handoff report:

```powershell
python .\run_health_report.py --base-url http://127.0.0.1:8000
```

The report includes preflight checks, migration state, storage paths, task and outbox counts, canonical counts, telemetry summary, release risk, and safe session diagnostics. It intentionally excludes raw X secrets, credential references, and lease tokens.
The `runtime_errors` section groups recent task failures by class, severity, scope, and recommended operator action.

## Capturing a New GraphQL Operation ID (New Capability Onboarding)

Every capability's `AcquisitionRecipeRevision.operation` pins a specific `operation_id` -- a short opaque string X assigns to each GraphQL persisted query (e.g. `SEARCH_TWEETS`'s `SearchTimeline` operation). X does not publish these; they only exist in the request URLs the real web app sends (`https://x.com/i/api/graphql/<operation_id>/<OperationName>`), and they rotate periodically. Onboarding any new capability requires capturing the real value from a live, authenticated browser session. This is manual, operator-driven work; nothing in this codebase automates it, and it must be done with an account the operator is authorized to use (see `playground/Twitter Research.md` §21 on credential handling -- never commit session cookies or tokens anywhere in this repo).

`TWEET_BY_ID`'s `TweetResultByRestId` operation ID (`GZsN2Pc4knAoit6pXa4HSA`) and full `feature_bundle` were captured this way on 2026-08-14 and are already in `protocol_releases/search_tweets.candidate.json`. The steps below are recorded for the next capability that needs the same treatment.

Procedure:

1. Sign in to x.com normally in a real browser, using an account you're authorized to use.
2. Open DevTools (F12) -> **Network** tab -> filter type to **Fetch/XHR**, and type `graphql` into the filter box so only GraphQL calls show.
3. Trigger the specific UI action that fires the operation you need. For `TweetResultByRestId` specifically, X calls it when the app needs exactly one tweet's data in isolation rather than a timeline -- reliable ways to trigger it: open a tweet that's quoted/embedded inside another tweet (click the quoted-tweet card), or open a tweet permalink reached via a link/share rather than by scrolling a timeline. If `TweetDetail` fires instead of `TweetResultByRestId`, that's the wrong operation (it returns a whole conversation, not a single object) -- try a different entry point until you see a request whose URL segment after `/graphql/` is followed by `/TweetResultByRestId`.
4. Click that request -> **Headers** tab. The URL looks like `https://x.com/i/api/graphql/AbCdEfGhIjKlMnOpQrStUv/TweetResultByRestId` -- the segment between `/graphql/` and the operation name is the `operation_id`.
5. While you're there, right-click the request -> **Copy** -> **Copy as cURL** to also capture the exact `variables`, `features`, and `fieldToggles` bodies and the request headers the real client sends. Compare these against `protocol_releases/search_tweets.candidate.json`'s `TWEET_BY_ID` binding's `feature_bundle` and `transaction_profile.required_headers` -- update those too if the live request no longer matches what's declared (this is exactly the kind of drift `validate_tweet_by_id_recipe_binding()` in `tweet_by_id.py` self-checks for).
6. Replace the placeholder `operation_id` in the manifest's binding with the captured value, and update `operation.status`/`evidence_maturity` from `DRAFT`/`INFERRED` to `CANDIDATE`/`OBSERVED` to reflect that it's now backed by a real capture (mirroring how `SEARCH_TWEETS`'s binding is annotated).

This only produces an `OBSERVED`, not yet `APPROVED`, recipe -- it still needs to pass fixture and capture-replay validation the way `SEARCH_TWEETS`'s did before promotion. As of this checkpoint, `protocol_validation.py`'s fixture/capture-replay pipeline is hardcoded to `SEARCH_TWEETS`'s fixture directory and parser (`docs/TASKS.md` tracks making it capability-parameterized), so that pipeline needs to support each new capability before it can reach `APPROVED` through the normal promotion safety gate.

## Verification Before Release

Run locally (requires `docker compose up -d` for the Postgres/Redis-backed suites; unreachable services cause those tests to skip rather than fail):

The Postgres-backed suites run against a dedicated `xingestion_test` database (`tests/postgres_fixture.py`'s default `XINGESTION_TEST_POSTGRES_DSN`), auto-created on first use, on the same local Postgres instance the live dev stack (`run_all.ps1`) uses -- `make_postgres_ledger()` `TRUNCATE`s `capability_tasks`/`outbox_events` on every call, so running the suite no longer wipes the live app's `xingestion` database out from under it. This isolation only holds as long as `XINGESTION_TEST_POSTGRES_DSN` is left unset or points somewhere other than `XINGESTION_POSTGRES_DSN`'s database -- don't point it at the live stack's database.

```powershell
python -m unittest discover -s tests
python -m compileall -q src tests run_app.py run_worker.py run_dispatcher.py run_migrations.py run_postgres_migrations.py run_smoke.py run_preflight.py run_health_report.py run_supervisor_check.py run_failed_task_export.py run_task_actions.py run_startup_check.py run_outbox.py run_protocol_validation.py run_sessions.py run_releases.py
```

`tests/test_delivery_load.py` (dispatcher/worker load, soak, and multi-consumer crash-recovery scenarios) is opt-in and skipped above by default. Run it separately, with no other `run_dispatcher.py`/`run_worker.py` pointed at the same Postgres database (they will race it for the same outbox rows):

```powershell
$env:XINGESTION_RUN_LOAD_TESTS = "1"
python -m unittest discover -s tests -p "test_delivery_load.py" -v
```

After starting infrastructure, web, worker, and dispatcher:

```powershell
python .\run_startup_check.py
python .\run_preflight.py --base-url http://127.0.0.1:8000
python .\run_supervisor_check.py --base-url http://127.0.0.1:8000 --expect-processes
python .\run_smoke.py --base-url http://127.0.0.1:8000
python .\run_smoke.py --base-url http://127.0.0.1:8000 --submit "india lang:en" --wait 90
python .\run_health_report.py --base-url http://127.0.0.1:8000
```

CI runs the same checks on Windows Python 3.11 and 3.12 (including frontend and secret-hygiene checks) plus a dedicated Postgres/Redis-backed job on Ubuntu with service containers.

See [process_supervision.md](process_supervision.md) for Windows Task Scheduler/NSSM examples and restart verification.
See [logging.md](logging.md) for rotating log file configuration.
