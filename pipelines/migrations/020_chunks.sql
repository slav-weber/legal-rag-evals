-- Citable chunks (design settled 2026-07-16).
--
-- A chunk is ONE citable unit of ONE edition — never a sliding window. Its key IS the
-- atom_id the plan defines: (act_nreg, unit_path, edition_date), with act_nreg CANONICAL
-- (3633-IX -> 3633-20). The canonical nreg lives ONLY here: units/editions/links keep their
-- native nreg, hence the separate src_act_nreg carrying the FK.
--
-- v0 scope: only the CURRENT in-force editions of the 11-act perimeter.
-- pgvector is deliberately absent — a later migration adds embeddings additively.

CREATE TABLE IF NOT EXISTS chunks (
    -- atom_id
    act_nreg        text        NOT NULL,   -- CANONICAL nreg (alias applied)
    unit_path       text        NOT NULL,
    edition_date    date        NOT NULL,

    -- link back to units: source-side key, in the NATIVE nreg those tables use
    src_act_nreg    text        NOT NULL,
    kind            text        NOT NULL,

    text            text        NOT NULL,   -- VERBATIM units.text (legal text is never edited)
    char_len        int         NOT NULL,
    n_tokens        int         NOT NULL,   -- real BGE-M3 tokenizer (pinned, see chunk.py)

    citation        text        NOT NULL,   -- pre-rendered «ст. 23 ч. 1 · ред. від 12.04.2026»
    act_title       text,

    -- temporal validity. v0 chunks only current in-force editions, so in_force_to IS NULL
    -- everywhere; the column exists now so a full temporal index and the retrieval layer's
    -- «редакція чинна на дату» (edition in force on a date) filter are ADDITIVE, not a
    -- schema break.
    in_force_from   date        NOT NULL,
    in_force_to     date,

    parser_version  text        NOT NULL,   -- provenance: which parser/tokenizer built this
    built_at        timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (act_nreg, unit_path, edition_date),

    -- A reparse does DELETE FROM units WHERE (act, edition) and re-inserts; chunks of a
    -- reparsed edition must die with it rather than dangle. Rebuild is a separate run.
    FOREIGN KEY (src_act_nreg, edition_date, unit_path)
        REFERENCES units (act_nreg, edition_date, unit_path) ON DELETE CASCADE,

    CONSTRAINT chunks_kind_known CHECK (kind IN
        ('preamble', 'section', 'chapter', 'article', 'point', 'annex', 'approved')),
    CONSTRAINT chunks_tokens_fit CHECK (n_tokens > 0 AND n_tokens <= 8192),
    CONSTRAINT chunks_text_nonempty CHECK (char_len > 0)
);

CREATE INDEX IF NOT EXISTS chunks_src_idx     ON chunks (src_act_nreg, edition_date);
CREATE INDEX IF NOT EXISTS chunks_inforce_idx ON chunks (in_force_from, in_force_to);
CREATE INDEX IF NOT EXISTS chunks_kind_idx    ON chunks (kind);
