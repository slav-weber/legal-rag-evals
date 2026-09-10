-- Retry lineage for --resume. A resumed run links back to the run it re-ran via
-- a self-FK; retry_count (reserved in 012) is populated on the resumed run's errors. Idempotent
-- DDL on the small ingest_runs table; decisions (696k+) untouched.
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS resumed_from BIGINT;
ALTER TABLE ingest_runs DROP CONSTRAINT IF EXISTS ingest_runs_resumed_from_fkey;
ALTER TABLE ingest_runs ADD CONSTRAINT ingest_runs_resumed_from_fkey
  FOREIGN KEY (resumed_from) REFERENCES ingest_runs (run_id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ingest_runs_resumed_from_idx ON ingest_runs (resumed_from)
  WHERE resumed_from IS NOT NULL;

COMMENT ON COLUMN ingest_runs.resumed_from IS
  'run_id this run RE-RAN (resume lineage). NULL for a first-attempt run.';
