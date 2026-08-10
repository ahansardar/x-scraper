CREATE TABLE IF NOT EXISTS protocol_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    recipe_revision_id TEXT NOT NULL,
    state TEXT NOT NULL,
    session_id TEXT,
    error_class TEXT,
    tweet_count INTEGER NOT NULL,
    next_cursor_present INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_protocol_attempts_release_created
ON protocol_attempts (release_id, created_at);
