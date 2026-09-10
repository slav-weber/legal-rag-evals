-- Following the ДСА (State Judicial Administration) reply of 2026-07-17: promote D-01 / D-07
-- into artifact_registry so the Data Atlas disk→manifest direction COVERS their new snapshot rows
-- instead of flagging them as disk_gaps. Exact precedent — migration 016, which promoted the 7
-- corpus snapshot artifacts: these are PRODUCT artifacts registered in the data registry, so per
-- the atlas OPS_ALLOWLIST rule they must be REGISTERED, not allowlisted (the allowlist is only
-- for non-product ops/probe snapshots).
--
-- Both arrived as attachments to ДСА letter № 8-14420/26 від 10.07.2026 and are registered in
-- `snapshots` by a one-off registration script (Excel in $DATA_DIR/raw/dsa/, sha256 in
-- SHA256SUMS). source_id NULL (email-received, not a machine-probed source); mod/version NULL
-- (no orchestrator collector yet — the parsers come later; registry-only for coverage, exactly as
-- 016's C-02/D-04). kind='fetch' (externally obtained snapshot, as the ДСА sibling D-04). Idempotent.
INSERT INTO artifact_registry (artifact_id, name, source_id, host, mod, version, kind) VALUES
  ('D-01', 'DSA court registry (addresses+email) — perelik sudiv XLSX', NULL, 'ics.gov.ua', NULL, NULL, 'fetch'),
  ('D-07', 'DSA monthly report — military pidsudnist aggregator XLSX',  NULL, 'ics.gov.ua', NULL, NULL, 'fetch')
ON CONFLICT (artifact_id) DO NOTHING;
