CREATE TABLE IF NOT EXISTS capability_tasks (
    task_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    capability_id TEXT NOT NULL,
    contract_version INTEGER NOT NULL,
    state TEXT NOT NULL,
    request_json TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    result_json TEXT,
    error_json TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_attempt_at TEXT,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    delivery_generation INTEGER NOT NULL DEFAULT 0,
    replay_origin_task_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT,
    FOREIGN KEY (task_id) REFERENCES capability_tasks(task_id)
);

CREATE INDEX IF NOT EXISTS idx_outbox_unpublished
ON outbox_events (published_at, created_at);

CREATE TABLE IF NOT EXISTS canonical_tweets (
    tweet_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    source_created_at TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    media_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS engagement_observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    reply_count INTEGER NOT NULL,
    repost_count INTEGER NOT NULL,
    like_count INTEGER NOT NULL,
    quote_count INTEGER NOT NULL,
    bookmark_count INTEGER NOT NULL,
    view_count TEXT,
    raw_evidence_id TEXT,
    release_id TEXT NOT NULL,
    recipe_revision_id TEXT NOT NULL,
    FOREIGN KEY (tweet_id) REFERENCES canonical_tweets(tweet_id)
);

CREATE INDEX IF NOT EXISTS idx_engagement_observations_tweet_time
ON engagement_observations (tweet_id, captured_at);

CREATE TABLE IF NOT EXISTS session_artifacts (
    session_id TEXT PRIMARY KEY,
    account_label TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    network_context TEXT NOT NULL,
    health TEXT NOT NULL,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS protocol_release_health (
    release_id TEXT PRIMARY KEY,
    health TEXT NOT NULL,
    reason TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
