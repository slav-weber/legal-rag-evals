-- edrnpa_cards — A-07 cross-validation table. One row per <document> card from the
-- EDRNPA cards XML (~143k): metadata for cross-checking our Rada corpus (completeness + current
-- in-force status; the dump has NO edition history). Surrogate BIGSERIAL PK + INDEX on
-- reestr_code; duplicate reestr_codes are KEPT deliberately — this is a cross-validation table,
-- not a dedup'd master. Populated by the standalone loader pipelines.edrnpa.parse_cards (TRUNCATE + reload,
-- idempotent). Metadata only (no ПІБ / act text). Idempotent DDL.
CREATE TABLE IF NOT EXISTS edrnpa_cards (
  id BIGSERIAL PRIMARY KEY,
  reestr_code TEXT,
  type TEXT,
  publisher TEXT,
  act_number TEXT,
  name TEXT,
  date_acc DATE,
  reestr_date DATE,
  status TEXT,
  reg_number TEXT,
  reg_date DATE
);
CREATE INDEX IF NOT EXISTS edrnpa_cards_reestr_code_idx ON edrnpa_cards (reestr_code);
