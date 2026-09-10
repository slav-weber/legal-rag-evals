-- Mark decisions whose text is TERMINALLY unfetchable — a 404/4xx, or a 200 that
-- decodes empty/mojibake — so the "fetchable" set (txt_path IS NULL) stops including
-- permanently-unfetchable rows. Without this, B-03/B-08 (edrsr/fetch_texts) can never reach a
-- clean exit 0: a handful of dead doc_urls keep `remaining` > 0 forever → eternal exit 1 →
-- the orchestrator journals B-03 as perpetually failed. Transient failures (429/5xx/network)
-- are NOT marked — they stay fetchable for retry on a later run.
-- Idempotent DDL.
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS fetch_status TEXT;  -- NULL = still fetchable; else the REASON string mark_terminal() stores, e.g. 'HTTP 404' / 'empty/mojibake'
CREATE INDEX IF NOT EXISTS decisions_fetch_status_idx ON decisions (fetch_status)
    WHERE fetch_status IS NOT NULL;
