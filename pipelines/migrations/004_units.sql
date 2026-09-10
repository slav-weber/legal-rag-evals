-- Structural units of a legislation edition (parser v0).
-- One row per recognised structural unit (preamble / section / article / point)
-- of a given act edition. unit_path is a stable, article-number-based key so the
-- same article diffs cleanly across editions (FRBR: article number is the anchor).
-- Idempotent DDL; the parser re-writes an edition by delete-then-insert.

CREATE TABLE IF NOT EXISTS units (
    act_nreg       TEXT NOT NULL,                 -- e.g. 3543-12
    edition_date   DATE NOT NULL,                 -- editions.edition_date
    unit_path      TEXT NOT NULL,                 -- stable key: преамбула | розд.VI-1 | ст.13-1 | ст.4/п.4
    kind           TEXT NOT NULL,                 -- 'preamble' | 'section' | 'article' | 'point'
    ordinal        INTEGER NOT NULL,              -- document order within the edition
    title          TEXT,                          -- article/section heading (NULL for points)
    text           TEXT NOT NULL,                 -- unit body (markers stripped from text, kept in inline_markers)
    inline_markers TEXT[] NOT NULL DEFAULT '{}',  -- {...} provenance spans found inside this unit
    char_len       INTEGER NOT NULL DEFAULT 0,    -- length(text), for cheap change detection
    PRIMARY KEY (act_nreg, edition_date, unit_path)
);

CREATE INDEX IF NOT EXISTS units_act_ed_idx ON units (act_nreg, edition_date);
CREATE INDEX IF NOT EXISTS units_kind_idx ON units (act_nreg, edition_date, kind);
