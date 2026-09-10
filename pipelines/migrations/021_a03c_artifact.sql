-- Seed A-03c (chunk build) into artifact_registry so the orchestrator can journal
-- it under the ingest_runs.artifact_id FK, and so the coherence lint (ARTIFACTS ⊆
-- artifact_registry) stays green. Without this row the artifact is unjournalable: run_one's FK
-- INSERT fails and `dev_setup --gate` reddens on registry drift.
--
-- WHY the artifact exists (decision of 2026-07-17): A-03b reparses EVERY edition (DELETE FROM
-- units per act+edition) and `chunks` holds an FK → units ON DELETE CASCADE, so the daily
-- `collect --all --run` destroyed the whole chunk layer (measured 2026-07-17: 4 706 → 0) and
-- nothing rebuilt it. kind='derived' — same class as A-03b (parse) and A-05 (links): no wire,
-- source_id 'rada' (its base's source). Idempotent, following migration 015.
INSERT INTO artifact_registry (artifact_id, name, source_id, host, mod, version, kind) VALUES
  ('A-03c', 'Rada chunks (build — derived)', 'rada', '(derived)', 'pipelines.rada.chunk', 'rada.chunk@1', 'derived')
ON CONFLICT (artifact_id) DO UPDATE SET
  name = EXCLUDED.name, source_id = EXCLUDED.source_id, host = EXCLUDED.host,
  mod = EXCLUDED.mod, version = EXCLUDED.version, kind = EXCLUDED.kind;
