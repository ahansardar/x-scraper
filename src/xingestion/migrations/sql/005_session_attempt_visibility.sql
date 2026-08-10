ALTER TABLE session_artifacts ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE session_artifacts ADD COLUMN success_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE session_artifacts ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE session_artifacts ADD COLUMN last_attempt_at TEXT;
ALTER TABLE session_artifacts ADD COLUMN last_success_at TEXT;
ALTER TABLE session_artifacts ADD COLUMN last_error_class TEXT;
ALTER TABLE session_artifacts ADD COLUMN last_error_message TEXT;
