-- Rada legislation FRBR skeleton.
-- acts = the Work identity + latest card; editions = each redaction (Expression).
-- Idempotent DDL: safe to run repeatedly.

CREATE TABLE IF NOT EXISTS acts (
    nreg       TEXT PRIMARY KEY,               -- Rada registration number, e.g. 3543-12
    title      TEXT,                           -- card.nazva
    type       TEXT,                           -- card.typ (classifier code)
    card_json  JSONB,                          -- full raw card (source of truth)
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS editions (
    act_nreg     TEXT NOT NULL REFERENCES acts (nreg) ON DELETE CASCADE,
    edition_date DATE NOT NULL,                -- parsed from eds[].datred (YYYYMMDD)
    pidstava     TEXT,                          -- amending act that produced this edition
    size         BIGINT,                        -- eds[].size (bytes of the edition text)
    txt_path     TEXT,                          -- local path to the fetched edition TXT (fetch_texts)
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (act_nreg, edition_date)        -- idempotency key
);

CREATE INDEX IF NOT EXISTS editions_act_idx ON editions (act_nreg);
