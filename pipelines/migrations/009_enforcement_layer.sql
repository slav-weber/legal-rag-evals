-- B-09 enforcement-layer promote. The ТЦК/mobilization-theme subset of category
-- 40050 (примусове виконання) / 41462 is promoted into `decisions` tagged as a
-- separate LAYER, so it is never confused with the main SLICE and can be excluded in
-- bulk. `confidence` lets downstream keep only HIGH-precision rows for citable use.
--   layer      NULL = the main slice · 'enforcement' = promoted 40050/41462 theme-subset
--   confidence 'HIGH' = a literal/high-precision theme token fired (ст.210-1 | ТЦК |
--              тер.центр комплектування) · 'LOW' = only a weaker token (мобіліз | призов
--              | військовий облік). NULL for main-slice rows.
-- Idempotent DDL.
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS layer      TEXT;
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS confidence TEXT;
CREATE INDEX IF NOT EXISTS decisions_layer_idx ON decisions (layer);
