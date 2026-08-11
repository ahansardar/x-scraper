CREATE TABLE IF NOT EXISTS approved_protocol_release (
  id TEXT PRIMARY KEY,
  release_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
