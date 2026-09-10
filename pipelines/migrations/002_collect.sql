-- Collection round 1 — card attachments (A-04) and act links (A-05).
-- Idempotent DDL.

CREATE TABLE IF NOT EXISTS attachments (
    act_nreg   TEXT NOT NULL REFERENCES acts (nreg) ON DELETE CASCADE,
    fname      TEXT NOT NULL,               -- card fname key, e.g. f535568n491.docx
    url        TEXT,                          -- resolved data.rada download URL
    sha256     TEXT,                          -- content hash (integrity + dedup)
    bytes      BIGINT,
    raw_path   TEXT,                          -- repo-relative POSIX path in data/raw
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (act_nreg, fname)
);

CREATE TABLE IF NOT EXISTS links (
    act_nreg   TEXT NOT NULL REFERENCES acts (nreg) ON DELETE CASCADE,
    related    TEXT NOT NULL,                 -- related/amending act (nreg or raw token)
    rel_type   TEXT NOT NULL,                 -- e.g. amended_by, basis
    detail     TEXT,                          -- date / note
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (act_nreg, related, rel_type)
);
