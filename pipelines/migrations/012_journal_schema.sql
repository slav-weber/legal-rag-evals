-- Journal-schema hardening — artifact registry + FK + CHECK on state + items_processed (the
-- items_ok split) + artifact_collections.run_id. Idempotent DDL on the SMALL journal tables
-- ONLY (ingest_runs ~46 rows, artifact_collections ~24); it does NOT touch decisions (696k+).
-- Follows the pattern set by migration 011.

-- 1) artifact_registry — the canonical list of EVERY artifact that writes an ingest_runs row:
--    the 7 orchestrated + the 2 self-journal collectors (T5-slice = filter_slice, B-05 =
--    tombstones). It is the FK target for ingest_runs.artifact_id. The Python ARTIFACTS dict
--    stays the runtime driver (what to run + args); a coherence lint checks
--    ARTIFACTS ⊆ this registry. source_id FKs to the existing source_registry.
CREATE TABLE IF NOT EXISTS artifact_registry (
    artifact_id  TEXT PRIMARY KEY,
    name         TEXT,
    source_id    TEXT REFERENCES source_registry(source_id),
    host         TEXT,
    mod          TEXT,
    version      TEXT,
    kind         TEXT CHECK (kind IN ('fetch', 'derived', 'self-journal'))
);

INSERT INTO artifact_registry (artifact_id, name, source_id, host, mod, version, kind) VALUES
  ('A-01',    'Rada seed cards',                   'rada',       'data.rada.gov.ua',          'pipelines.rada.fetch_cards',       'rada.fetch_cards@1',       'fetch'),
  ('A-03',    'Rada edition texts',                'rada',       'data.rada.gov.ua',          'pipelines.rada.fetch_texts',       'rada.fetch_texts@1',       'fetch'),
  ('A-03b',   'Rada units (parse — derived)',      'rada',       '(derived)',                 'pipelines.rada.parse_structure',   'rada.parse_structure@1',   'derived'),
  ('A-04',    'Rada attachments',                  'rada',       'data.rada.gov.ua',          'pipelines.rada.fetch_attachments', 'rada.fetch_attachments@1', 'fetch'),
  ('A-05',    'Rada links graph (derived)',        'rada',       '(derived)',                 'pipelines.rada.fetch_links',       'rada.fetch_links@1',       'derived'),
  ('B-01',    'EDRSR yearly dumps',                'ckan-edrsr', 'data.gov.ua',               'pipelines.edrsr.fetch_dumps',      'edrsr.fetch_dumps@1',      'fetch'),
  ('B-03',    'EDRSR decision texts',              'ckan-edrsr', 'od.reyestr.court.gov.ua',   'pipelines.edrsr.fetch_texts',      'edrsr.fetch_texts@1',      'fetch'),
  ('T5-slice','EDRSR hero-slice filter (self)',    'ckan-edrsr', '(local)',                   'pipelines.edrsr.filter_slice',     'edrsr.filter_slice@1',     'self-journal'),
  ('B-05',    'EDRSR tombstones sync (self)',      'ckan-edrsr', '(local)',                   'pipelines.edrsr.tombstones',       'edrsr.tombstones@1',       'self-journal')
ON CONFLICT (artifact_id) DO UPDATE SET
  name = EXCLUDED.name, source_id = EXCLUDED.source_id, host = EXCLUDED.host,
  mod = EXCLUDED.mod, version = EXCLUDED.version, kind = EXCLUDED.kind;

-- 2) ingest_runs — host, the FK to the registry, a CHECK on state, and the items_processed
--    column: items_ok stays = NEW rows (delta, 0 on no-new); items_processed = the
--    collector's COLLECT-SUMMARY ok= (work done, may be >0 on a refresh). Split done in code.
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS host TEXT;
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS items_processed INTEGER;

-- backfill host from the registry for existing rows (idempotent — only fills NULLs).
UPDATE ingest_runs r SET host = a.host
  FROM artifact_registry a WHERE r.artifact_id = a.artifact_id AND r.host IS NULL;

-- FK ingest_runs.artifact_id -> artifact_registry (drop+add = idempotent; the 8 existing
-- artifact_ids, incl. T5-slice, are all seeded above so validation passes).
ALTER TABLE ingest_runs DROP CONSTRAINT IF EXISTS ingest_runs_artifact_id_fkey;
ALTER TABLE ingest_runs ADD CONSTRAINT ingest_runs_artifact_id_fkey
  FOREIGN KEY (artifact_id) REFERENCES artifact_registry (artifact_id);

-- CHECK on state — every existing value (ok/no-new/failed/dry-run) plus the runtime states
-- (running at creation, deferred on a planned budget stop) passes.
ALTER TABLE ingest_runs DROP CONSTRAINT IF EXISTS ingest_runs_state_check;
ALTER TABLE ingest_runs ADD CONSTRAINT ingest_runs_state_check
  CHECK (state IN ('ok', 'no-new', 'failed', 'deferred', 'running', 'dry-run'));

-- 3) artifact_collections — run_id FK (nullable: legacy rows keep NULL). bytes/parser_version
--    columns already exist; the orchestrator now WRITES them (and a DATA_DIR-relative
--    raw_snapshot_path). Legacy absolute paths are normalised honestly in code, not blindly.
ALTER TABLE artifact_collections ADD COLUMN IF NOT EXISTS run_id BIGINT;
ALTER TABLE artifact_collections DROP CONSTRAINT IF EXISTS artifact_collections_run_id_fkey;
ALTER TABLE artifact_collections ADD CONSTRAINT artifact_collections_run_id_fkey
  FOREIGN KEY (run_id) REFERENCES ingest_runs (run_id) ON DELETE SET NULL;

-- 4) ingest_errors — resolved IS implemented in code (a later successful run of the same
--    artifact clears its prior open errors). retry_count is RESERVED for the --resume package.
COMMENT ON COLUMN ingest_errors.retry_count IS
  'RESERVED. Populated by the resume package retry tracking, stays 0 until then.';
COMMENT ON COLUMN ingest_errors.resolved IS
  'TRUE once a later successful run of the same artifact clears this error (collect._resolve_prior_errors).';
COMMENT ON COLUMN ingest_runs.items_ok IS
  'NEW rows landed in the target table this run (validator delta). 0 on no-new/failed/deferred.';
COMMENT ON COLUMN ingest_runs.items_processed IS
  'items the collector reported processing (COLLECT-SUMMARY ok=). Work done, may be >0 on a no-new refresh.';
