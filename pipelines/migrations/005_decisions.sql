-- EDRSR court-decision metadata slice.
-- One row per court decision in the main-topic slice (filtered from the yearly
-- documents.csv dumps). Metadata only + a local path to the normalised text;
-- decision TEXTS (PII) live under DATA_DIR, never in git or Postgres columns.
-- `judge` (ПІБ) from the dump is deliberately NOT stored — not needed for the
-- slice and keeps PII out of the DB.
-- Idempotent DDL.

CREATE TABLE IF NOT EXISTS decisions (
    doc_id            BIGINT PRIMARY KEY,        -- ЄДРСР document id
    court_code        INTEGER,                   -- courts.csv
    judgment_code     INTEGER,                   -- judgment_forms.csv (2=Постанова, 3=Рішення, 5=Ухвала…)
    justice_kind      INTEGER,                   -- justice_kinds.csv (4=Адміністративне)
    category_code     INTEGER,                   -- cause_categories.csv (13788, 40167…)
    cause_num         TEXT,                      -- case number, e.g. 620/7437/25
    adjudication_date DATE,
    receipt_date      DATE,
    doc_url           TEXT,                      -- od.reyestr RTF/HTML url
    status            SMALLINT,                  -- 1 = active, 0 = tombstoned (withdrawn)
    year              SMALLINT,                  -- source dump year
    txt_path          TEXT,                      -- DATA_DIR-relative POSIX to normalised text
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS decisions_category_idx ON decisions (category_code);
CREATE INDEX IF NOT EXISTS decisions_court_idx ON decisions (court_code);
CREATE INDEX IF NOT EXISTS decisions_status_idx ON decisions (status);
CREATE INDEX IF NOT EXISTS decisions_cat_year_idx ON decisions (category_code, year);
