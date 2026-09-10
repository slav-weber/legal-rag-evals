-- The lemma channel (MORPHOLOGY ONLY — the special-token work is deferred, with a plan).
-- A content-hash-keyed lemma_cache, mirroring embeddings (023): it survives the daily A-03c
-- DELETE+INSERT of chunks (NO FK to chunks) and is near-no-op on a bit-identical rebuild, so a
-- quiet day costs 0 re-lemmatisations.
--
-- The key (content_hash, pipeline_version): pipeline_version = the DICTIONARY version and the
-- TOKENIZER version together, so changing EITHER forces a clean rebuild (the same pinning
-- discipline as the embedder). Not dict_version alone — otherwise a tokenizer change (e.g. when
-- the special-token work lands) would not invalidate the cache. pipeline_version lives in
-- ml/lemma_index.PIPELINE_VERSION.
CREATE TABLE IF NOT EXISTS lemma_cache (
    content_hash     text        NOT NULL,   -- = chunks.content_hash (sha256 of the raw text)
    pipeline_version text        NOT NULL,   -- dict_version + tokenizer_version
    lemma_tsv        tsvector    NOT NULL,    -- to_tsvector('simple', lemmatised text)
    built_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (content_hash, pipeline_version)
);
CREATE INDEX IF NOT EXISTS lemma_cache_gin ON lemma_cache USING gin (lemma_tsv);

-- A-03e registry row (following A-03d in 023): the orchestrator journals the build, and the
-- coherence lint stays green.
INSERT INTO artifact_registry (artifact_id, name, source_id, host, mod, version, kind) VALUES
  ('A-03e', 'Rada chunk lemmas (build — derived)', 'rada', '(derived)', 'ml.lemma_index', 'ml.lemma_index@1', 'derived')
ON CONFLICT (artifact_id) DO UPDATE SET
  name = EXCLUDED.name, source_id = EXCLUDED.source_id, host = EXCLUDED.host,
  mod = EXCLUDED.mod, version = EXCLUDED.version, kind = EXCLUDED.kind;
