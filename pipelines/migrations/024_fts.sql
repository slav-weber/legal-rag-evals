-- The FTS channel of hybrid retrieval: a simple-tsvector over the chunk's legal text + GIN.
-- Decision: the 'simple' configuration (no stemming); hunspell is NOT introduced — the lemma
-- channel added in 025 covers morphology and the special tokens. The pgvector/pgvector:pg17
-- image is left untouched: 'simple' is built in. Additive, like content_hash in 023.
--
-- to_tsvector('simple', text) is IMMUTABLE (the 2-arg form with a CONSTANT configuration;
-- verified live). NOT the 1-arg to_tsvector(text) — that one is STABLE (it depends on the GUC
-- default_text_search_config) and is unusable in a generated column: exactly the convert_to
-- trap from the previous migration.
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS text_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED;
CREATE INDEX IF NOT EXISTS chunks_text_tsv_gin ON chunks USING gin (text_tsv);

-- chunks_indexable is a VIEW created in 023 with `SELECT c.*`; Postgres EXPANDS the * at CREATE
-- time, so text_tsv (added just now) is NOT in the view yet. Recreate it so the FTS channel can
-- read ci.text_tsv directly. CREATE OR REPLACE is legal here: text_tsv is appended at the END of
-- chunks, and OR REPLACE permits adding new columns only at the end. Predicate unchanged.
CREATE OR REPLACE VIEW chunks_indexable AS
  SELECT c.* FROM chunks c
  WHERE NOT EXISTS (
    SELECT 1 FROM chunks k
    WHERE k.act_nreg = c.act_nreg AND k.edition_date = c.edition_date
      AND k.unit_path LIKE c.unit_path || '/%');
