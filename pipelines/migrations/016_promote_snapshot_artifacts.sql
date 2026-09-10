-- Promote the 7 corpus snapshot artifacts that had files on disk (snapshots) but no
-- artifact_registry row, so the Data Atlas disk-to-manifest direction covers them instead of
-- flagging them forever. Their rows already exist in the data registry; this closes the
-- machine-mirror gap. The 3 ops/probe snapshots (F1-rada-rtxt, R-04, R-22-ogd) are handled by
-- the atlas OPS_ALLOWLIST, NOT promoted — they are legitimately not product artifacts.
-- source_id is NULL (these are not machine-probed sources);
-- mod/version NULL (not orchestrator collectors, registry-only for coverage). C-04 is derived from
-- B-08, the rest are fetched snapshots. Idempotent.
INSERT INTO artifact_registry (artifact_id, name, source_id, host, mod, version, kind) VALUES
  ('C-02', 'VS KAS ohlyad viiskova sluzhba (PDF)',        NULL, 'court.gov.ua',         NULL, NULL, 'fetch'),
  ('C-04', 'Zrazkovi spravy VS (art.290 KAS) registry',   NULL, 'supreme.court.gov.ua', NULL, NULL, 'derived'),
  ('D-04', 'DSA classifier (nakaz 622) PDF plus XLS',      NULL, 'court.gov.ua',         NULL, NULL, 'fetch'),
  ('E-02', 'WikiLegalAid zrazok klopotannia (DOCX)',       NULL, 'legalaid.wiki',        NULL, NULL, 'fetch'),
  ('E-03', 'Court subdomain zrazky (E-03 HTML)',           NULL, 'court.gov.ua',         NULL, NULL, 'fetch'),
  ('E-04', 'Rezerv plus and Diia official instructions',   NULL, 'guide.diia.gov.ua',    NULL, NULL, 'fetch'),
  ('E-05', 'WikiLegalAid hero-theme consultations',        NULL, 'legalaid.wiki',        NULL, NULL, 'fetch')
ON CONFLICT (artifact_id) DO NOTHING;

-- NOTE: E-03 carries one dead snapshot row from the pre-correction wrong path
-- (oda.arbitr.gov.ua/sud5037/doc/22, raw_path NULL, bytes NULL) superseded by the corrected
-- gromadyanam/doc/22 (raw_path present). Drop the orphan so E-03 disk data is coherent. Idempotent.
DELETE FROM snapshots WHERE artifact_id = 'E-03' AND raw_path IS NULL;
