CREATE TABLE IF NOT EXISTS capability_tasks (
    task_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    capability_id TEXT NOT NULL,
    contract_version INTEGER NOT NULL,
    state TEXT NOT NULL,
    request_json JSONB NOT NULL,
    plan_json JSONB NOT NULL,
    result_json JSONB,
    error_json JSONB,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_attempt_at TIMESTAMPTZ,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    delivery_generation INTEGER NOT NULL DEFAULT 0,
    replay_origin_task_id TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_capability_tasks_state_next_attempt
    ON capability_tasks (state, next_attempt_at);

CREATE INDEX IF NOT EXISTS idx_capability_tasks_state_lease_expiry
    ON capability_tasks (state, lease_expires_at);

CREATE INDEX IF NOT EXISTS idx_capability_tasks_capability_state
    ON capability_tasks (capability_id, state);

CREATE INDEX IF NOT EXISTS idx_capability_tasks_plan_release_id
    ON capability_tasks ((plan_json ->> 'release_id'));

CREATE TABLE IF NOT EXISTS outbox_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES capability_tasks(task_id),
    event_type TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_outbox_unpublished
    ON outbox_events (published_at, created_at);
