-- B-02 EDRSR reference books — 6 tables. The yearly dump (B-01) extracts 6 reference
-- CSVs per year to raw/edrsr/reference/<year>/. 2026 == union across 2022-2026 (verified), so a
-- single CURRENT table per book, no yearly versioning. DDL only here (data load = the orchestrated
-- collector pipelines.edrsr.load_reference, artifact B-02). Idempotent: CREATE IF NOT EXISTS with
-- inline PK + inline intra-reference FK (edrsr_courts to instances/regions, both 0 orphans).
-- PK types match decisions (INTEGER) for FK-type-parity in 018. region_code is TEXT (zero-padded
-- 01..31). Parents created before edrsr_courts so its inline FKs resolve.
CREATE TABLE IF NOT EXISTS edrsr_regions (
  region_code TEXT PRIMARY KEY,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edrsr_instances (
  instance_code INTEGER PRIMARY KEY,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edrsr_justice_kinds (
  justice_kind INTEGER PRIMARY KEY,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edrsr_judgment_forms (
  judgment_code INTEGER PRIMARY KEY,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edrsr_cause_categories (
  category_code INTEGER PRIMARY KEY,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edrsr_courts (
  court_code INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  instance_code INTEGER REFERENCES edrsr_instances (instance_code),
  region_code TEXT REFERENCES edrsr_regions (region_code)
);
-- machine mirror (coherence lint): B-02 is now an orchestrated load artifact, not a byproduct.
INSERT INTO artifact_registry (artifact_id, name, source_id, host, mod, version, kind) VALUES
  ('B-02', 'EDRSR reference books (6)', 'ckan-edrsr', '(derived)', 'pipelines.edrsr.load_reference', 'edrsr.load_reference@1', 'derived')
ON CONFLICT (artifact_id) DO NOTHING;
