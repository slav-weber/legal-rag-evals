-- External reference snapshots (D-04, E-02..E-05, C-02). Internal-only sources
-- kept with hash + date for freshness tracking. Idempotent DDL.

CREATE TABLE IF NOT EXISTS snapshots (
    artifact_id TEXT NOT NULL,               -- data-registry ID, e.g. D-04, E-04, C-02
    url         TEXT NOT NULL,
    sha256      TEXT,
    bytes       BIGINT,
    kind        TEXT,                          -- pdf / xls / docx / html
    http_status INT,
    raw_path    TEXT,                          -- DATA_DIR-relative POSIX
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (artifact_id, url)
);
