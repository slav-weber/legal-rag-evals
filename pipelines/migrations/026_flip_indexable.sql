-- Flip the VIEW — containers go into the index. A live measurement showed a dense p@1 lift with
-- containers included (distinctive .900→1.000, paraphrase .846→.923; recall and citation
-- unchanged). The "lift → flip" criterion was declared in advance and met, so chunks_indexable =
-- ALL chunks: the container-exclusion predicate introduced in 024 is dropped.
--
-- A container = a chunk that has a strict descendant (its text aggregates the ст.N/* leaves);
-- now both it and its leaves are servable. On an exact lookup the container ст.N (the whole
-- article) comes out #1, its leaves right after (ORDER BY unit_path). Embeddings for the 606
-- containers were back-filled once; the lemmas are back-filled by the next A-03e run
-- (missing_hashes is scoped to the VIEW, so it sees them itself).
--
-- ⚠ NB for the generation layer: with containers in the index, KIND-AWARE DEDUP when assembling
-- generation context is MANDATORY — a container and its leaves duplicate the same text.
-- Reverting is cheap: restore the NOT EXISTS predicate from 024 via CREATE OR REPLACE.
CREATE OR REPLACE VIEW chunks_indexable AS
  SELECT c.* FROM chunks c;
