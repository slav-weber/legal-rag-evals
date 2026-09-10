-- The RAG/retrieval path must consume ONLY the
-- HIGH-confidence citable core: the enforcement LAYER's LOW tier (730 rows) is a
-- reduced-precision auxiliary set and must never dilute a paid report's citations.
-- Making it a VIEW keeps the guarantee structural (no caller has to remember the filter).
-- decisions_citable (007) = status=1; this narrows it to layer IS NULL (main corpus) OR
-- confidence='HIGH' (enforcement HIGH tier). Idempotent DDL.
CREATE OR REPLACE VIEW decisions_citable_rag AS
    SELECT * FROM decisions
    WHERE status = 1 AND (layer IS NULL OR confidence = 'HIGH');
