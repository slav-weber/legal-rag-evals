-- Hardening pass, 2026-07-06. Structural guarantees that must not depend on
-- every caller remembering a WHERE clause. Idempotent DDL.

-- Citation gate. A tombstoned decision (status=0, «вилучено з реєстру») must
-- NEVER be citable in a paid report (product rule). The retrieval/citation layer
-- reads ONLY from this view, so the guarantee is structural, not procedural: the
-- tombstone flip removes the row from the citable set automatically. tombstones.py
-- additionally NULLs txt_path + quarantines the text file (defence-in-depth + PII).
CREATE OR REPLACE VIEW decisions_citable AS
    SELECT * FROM decisions WHERE status = 1;
