-- Ingest orchestrator + freshness tracking.
-- Built ALONGSIDE the existing collectors (fetch_cards/fetch_texts/fetch_dumps/
-- filter_slice) — they are NOT migrated onto it yet (pending review). This adds
-- the run journal, the machine mirror of the registry, and the freshness log.
-- Idempotent DDL.

-- Machine mirror of the data registry (source freshness signals).
CREATE TABLE IF NOT EXISTS source_registry (
    source_id          TEXT PRIMARY KEY,          -- e.g. 'rada', 'ckan-edrsr', 'hf-edrsr-kas'
    name               TEXT NOT NULL,
    url                TEXT,                       -- probe / base url
    probe_kind         TEXT NOT NULL,              -- rada_rtxt | ckan | hf | listing_hash | page_hash | manual
    probe_params       JSONB NOT NULL DEFAULT '{}',
    cadence            TEXT,                       -- daily | weekly | monthly
    staleness_slo_days INTEGER,
    license            TEXT
);

-- Journal of freshness probes.
CREATE TABLE IF NOT EXISTS source_checks (
    id           BIGSERIAL PRIMARY KEY,
    source_id    TEXT NOT NULL REFERENCES source_registry (source_id) ON DELETE CASCADE,
    checked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    signal_value TEXT,                             -- last-modified / metadata_modified / sha / hash
    changed      BOOLEAN,                          -- vs the previous check
    note         TEXT
);
CREATE INDEX IF NOT EXISTS source_checks_src_idx ON source_checks (source_id, checked_at DESC);

-- One row per orchestrator run of an artifact.
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id         BIGSERIAL PRIMARY KEY,
    artifact_id    TEXT NOT NULL,                  -- registry id, e.g. 'A-03', 'B-01'
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    state          TEXT NOT NULL DEFAULT 'running', -- running | ok | failed | deferred | dry-run
    items_ok       INTEGER NOT NULL DEFAULT 0,
    items_failed   INTEGER NOT NULL DEFAULT 0,
    bytes          BIGINT NOT NULL DEFAULT 0,
    parser_version TEXT,
    note           TEXT
);
CREATE INDEX IF NOT EXISTS ingest_runs_artifact_idx ON ingest_runs (artifact_id, started_at DESC);

CREATE TABLE IF NOT EXISTS ingest_errors (
    id          BIGSERIAL PRIMARY KEY,
    run_id      BIGINT NOT NULL REFERENCES ingest_runs (run_id) ON DELETE CASCADE,
    item_key    TEXT,
    http_status INTEGER,
    error       TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    resolved    BOOLEAN NOT NULL DEFAULT FALSE
);

-- Every registry row at every collection (freshness + provenance).
CREATE TABLE IF NOT EXISTS artifact_collections (
    id                BIGSERIAL PRIMARY KEY,
    artifact_id       TEXT NOT NULL,
    collected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    rows              BIGINT,
    bytes             BIGINT,
    parser_version    TEXT,
    raw_snapshot_path TEXT
);
CREATE INDEX IF NOT EXISTS artifact_collections_idx ON artifact_collections (artifact_id, collected_at DESC);
