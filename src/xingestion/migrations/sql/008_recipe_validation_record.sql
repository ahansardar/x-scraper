CREATE TABLE IF NOT EXISTS recipe_validation_record (
  record_id TEXT PRIMARY KEY,
  release_id TEXT NOT NULL,
  recipe_revision_id TEXT NOT NULL,
  composition_hash TEXT NOT NULL,
  runtime_version TEXT NOT NULL,
  validation_type TEXT NOT NULL,
  ok INTEGER NOT NULL,
  summary TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recipe_validation_record_release_recipe
ON recipe_validation_record (release_id, recipe_revision_id, created_at);
