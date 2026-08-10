CREATE TABLE IF NOT EXISTS reprocess_jobs (
    job_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    state TEXT NOT NULL,
    matched_tasks INTEGER NOT NULL,
    processed_tasks INTEGER NOT NULL,
    failed_tasks INTEGER NOT NULL,
    error_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
