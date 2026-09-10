-- FK from decisions to the reference books, ONLY where the orphan-audit found 0
-- orphans: category_code and justice_kind → VALID FK. court_code (0 real orphans, INT=INT) and
-- judgment_code (2 decisions, code 15) get NO hard FK — the decision was to keep the append-only
-- collect resilient (the yearly courts.csv lags relocated/added courts D-07; a VALID FK would drop
-- an INSERT on the first new court). A soft coherence lint reports the live numbers instead.
-- NB: the design sketch said court_code had 165/151867 orphans — that was a ZERO-PAD string
-- artifact (courts.csv "0201" vs INTEGER 201); the real figure is 0, since verified. Both FK
-- columns are nullable and a FK ignores NULLs. Idempotent (the runner applies ALL migrations every
-- time and ADD CONSTRAINT has no IF NOT EXISTS): DROP CONSTRAINT IF EXISTS, then ADD.
ALTER TABLE decisions DROP CONSTRAINT IF EXISTS decisions_category_code_fkey;
ALTER TABLE decisions ADD CONSTRAINT decisions_category_code_fkey
  FOREIGN KEY (category_code) REFERENCES edrsr_cause_categories (category_code);
ALTER TABLE decisions DROP CONSTRAINT IF EXISTS decisions_justice_kind_fkey;
ALTER TABLE decisions ADD CONSTRAINT decisions_justice_kind_fkey
  FOREIGN KEY (justice_kind) REFERENCES edrsr_justice_kinds (justice_kind);
