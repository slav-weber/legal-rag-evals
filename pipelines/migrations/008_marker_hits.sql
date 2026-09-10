-- B-09 marker-pass audit store. One row per (decision, marker) that fired, so the
-- ТЦК/mobilization + enforcement-in-case subsets are reproducible and auditable
-- (which marker matched which decision). doc_id is the public ЄДРСР id (no PII);
-- the decision TEXT is never stored here. Idempotent DDL.
CREATE TABLE IF NOT EXISTS marker_hits (
    doc_id             BIGINT NOT NULL,
    marker_set_version TEXT   NOT NULL,          -- versioned marker set (e.g. b09-v1)
    theme              TEXT   NOT NULL,          -- 'enforcement' | 'tck_delivery'
    marker_key         TEXT   NOT NULL,          -- which named marker matched
    scanned_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_id, marker_set_version, marker_key)
);
CREATE INDEX IF NOT EXISTS marker_hits_theme_idx
    ON marker_hits (marker_set_version, theme);
