-- BGE-M3 embedding index.
-- pgvector was NOT enabled before this (checked: plpgsql only); the image is
-- pgvector/pgvector:pg17, where the extension is available.
CREATE EXTENSION IF NOT EXISTS vector;

-- content_hash — a MODEL-AGNOSTIC content key: sha256 of the RAW text, not of (model‖prefix).
-- That way the chunk layer knows nothing about the model: when the model changes, two caches
-- coexist keyed by e.model, and the join stays chunks.content_hash = e.text_hash AND e.model =
-- the pin from .env. GENERATED STORED — one writer (the text itself); the A-03c INSERT does not
-- list this column, so a chunk rebuild leaves it unchanged.
-- text::bytea (NOT convert_to(...): that is STABLE, and a generated column needs IMMUTABLE) — on
-- a UTF8 server_encoding these are exactly the UTF-8 bytes, verified byte-for-byte against
-- python hashlib.sha256(text.encode()).
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_hash text
    GENERATED ALWAYS AS (encode(sha256(text::bytea), 'hex')) STORED;
CREATE INDEX IF NOT EXISTS chunks_content_hash_idx ON chunks (content_hash);

-- passage-vector CACHE. PK = (model, text_hash). Holds ONLY passage vectors (query vectors are
-- ephemeral and never cached); the prefix is fixed by a column + CHECK as a table invariant.
-- NO FK to chunks (the cascade is deliberately broken): the daily A-03c DELETE+INSERT of chunks
-- does NOT touch the cache; a bit-identical rebuild yields the same content_hash values, hence
-- 0 re-embeddings. Orphaned rows are a harmless cache (GC deferred to the backlog — to be run
-- with a report, not inside A-03d).
CREATE TABLE IF NOT EXISTS embeddings (
    model      text         NOT NULL,
    text_hash  text         NOT NULL,                                   -- = chunks.content_hash
    prefix     text         NOT NULL DEFAULT 'passage: ' CHECK (prefix = 'passage: '),
    dim        int          NOT NULL CHECK (dim = 1024),                -- schema-critical
    embedding  vector(1024) NOT NULL,                                   -- mean-pool (LM Studio) + L2
    built_at   timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (model, text_hash)
);
CREATE INDEX IF NOT EXISTS embeddings_hnsw ON embeddings USING hnsw (embedding vector_cosine_ops);

-- kind scope of the index: NON-duplicating chunks (leaves + childless ones); the 606 duplicating
-- containers are excluded — the diffuse vector of a whole article is worse than a precise child
-- one. Reversible: change the decision = edit the VIEW, and A-03d fills in the missing hashes.
-- The predicate is the same one the chunker and the citation gate use.
CREATE OR REPLACE VIEW chunks_indexable AS
  SELECT c.* FROM chunks c
  WHERE NOT EXISTS (
    SELECT 1 FROM chunks k
    WHERE k.act_nreg = c.act_nreg AND k.edition_date = c.edition_date
      AND k.unit_path LIKE c.unit_path || '/%');

-- A-03d registry row (following 021 for A-03c): so the orchestrator can journal the build and the
-- coherence lint (ARTIFACTS ⊆ artifact_registry) stays green. derived (as A-03b/A-03c), source rada.
INSERT INTO artifact_registry (artifact_id, name, source_id, host, mod, version, kind) VALUES
  ('A-03d', 'Rada chunk embeddings (build — derived)', 'rada', '(derived)', 'ml.embed_index', 'ml.embed_index@1', 'derived')
ON CONFLICT (artifact_id) DO UPDATE SET
  name = EXCLUDED.name, source_id = EXCLUDED.source_id, host = EXCLUDED.host,
  mod = EXCLUDED.mod, version = EXCLUDED.version, kind = EXCLUDED.kind;
