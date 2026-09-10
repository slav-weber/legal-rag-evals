-- Indexes supporting the FKs added in 012. Zero effect at current
-- volumes (journal tables are tiny), added for correctness/scale hygiene. Idempotent.
CREATE INDEX IF NOT EXISTS artifact_collections_run_id_idx ON artifact_collections (run_id);
CREATE INDEX IF NOT EXISTS artifact_registry_source_id_idx ON artifact_registry (source_id);
