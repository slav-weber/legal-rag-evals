-- Seed the 4 edrsr-family collectors into artifact_registry so
-- the orchestrator can journal them under the ingest_runs.artifact_id FK. A-07/B-07 are FILE
-- collectors (validated on disk); C-01/C-03 write the snapshots table; C-03 (ksu) is Rada
-- byte-metered. All source_ids already exist in source_registry. Idempotent.
INSERT INTO artifact_registry (artifact_id, name, source_id, host, mod, version, kind) VALUES
  ('A-07', 'EDRNPA dump (Minjust)',        'ckan-edrnpa',   'data.gov.ua',            'pipelines.edrnpa.fetch_dump',   'edrnpa.fetch_dump@1',   'fetch'),
  ('B-07', 'HF edrsr-kas slice',           'hf-edrsr-kas',  'huggingface.co',         'pipelines.hf.fetch_slice',      'hf.fetch_slice@1',      'fetch'),
  ('C-01', 'Supreme Court oglyady (PDF)',  'supreme-court', 'supreme.court.gov.ua',   'pipelines.freshness.vs_watcher','freshness.vs_watcher@1','fetch'),
  ('C-03', 'KSU decision snapshots',       'rada',          'data.rada.gov.ua',       'pipelines.ksu.snapshot',        'ksu.snapshot@1',        'fetch')
ON CONFLICT (artifact_id) DO UPDATE SET
  name = EXCLUDED.name, source_id = EXCLUDED.source_id, host = EXCLUDED.host,
  mod = EXCLUDED.mod, version = EXCLUDED.version, kind = EXCLUDED.kind;
