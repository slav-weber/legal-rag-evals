"""Build citable chunks from units (design settled 2026-07-16).

A chunk is ONE citable unit of ONE edition (стаття / частина / пункт / додаток …), never a
sliding window: `atom_id` = (act_nreg, unit_path, edition_date) with a CANONICAL act_nreg.
That is what makes the citation gate structural — a citation can only name an id that a
retrieved chunk actually has.

Reads `units`, writes ONLY `chunks`. Never touches units/editions/links.

Decisions this implements:
  · option A — every unit with its own text is a chunk (the article AND its частини), not
    leaves-only. Cost measured, not guessed: ×1.15 chunks / ×1.72 chars vs leaves-only.
    ⚠ Consequence, deliberate: a body-bearing CONTAINER (розд.XIII, 70 685 chars) duplicates
    the text of its children. Any consumer (the retrieval layer) MUST be kind-aware or it
    double-counts content. Flagged here because the schema cannot express it.
  · oversize (> 8192 BGE-M3 tokens) → represented by its children; an oversize LEAF is a
    hard-fail, reported by name, never silently truncated.
  · real BGE-M3 tokenizer, pinned by revision + sha256 (a proxy was measured and rejected:
    chars/token min 2.135 / median 4.344, so a safe proxy is 2× stricter than reality).
  · canonical nreg ONLY here (3633-IX -> 3633-20), sourced from the existing alias map —
    one writer per fact.
  · Europe/Kyiv for "today", via AT TIME ZONE — not CURRENT_DATE (which is the container's UTC).

Run:
  uv run python -m pipelines.rada.chunk --build     # rebuild chunks for the perimeter
  uv run python -m pipelines.rada.chunk --verify    # resolve every chunk back to a unit
  uv run python -m pipelines.rada.chunk --sample 10 --seed 20260716    # acceptance sample
"""

from __future__ import annotations

import argparse
import hashlib
import random
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines import summary as _summary  # noqa: E402
from pipelines.db import connect  # noqa: E402

# ── perimeter ────────────────────────────────────────────────────────────────────────
# 11 nreg (scope extended 2026-07-16). NOT SEED_ACTS: that list carries the archive
# volumes 80731/80732-10 (historical layer) and lacks 4695-20. 76-2024-п is provenance only.
PERIMETER = ("3543-12", "2232-12", "8073-10", "2747-15", "3674-17", "3633-IX",
             "1404-19", "4695-20", "560-2024-п", "z1109-08", "76-2023-п")

WINDOW = 8192          # BGE-M3 context
KYIV = "Europe/Kyiv"

# The floor A-03c's validator holds the rebuilt layer to — the count measured and accepted on
# 2026-07-16 (4 927 units − 205 ineligible − 16 oversize). Lives HERE, next to the perimeter
# that determines it, so the orchestrator's validator reads it from the chunker instead of
# carrying its own copy. (`dev_setup` COUNTERS keeps its own literal on purpose — the gate must
# not import the chunker to boot; a drifting FLOOR is loud there, unlike drifting SQL.)
CHUNKS_FLOOR = 4706

# ── tokenizer pin ────────────────────────────────────────────────────────────────────
# The 8192 gate is only as trustworthy as the tokenizer behind it: pin the ARTEFACT, not the
# model name — the pin must hold the artefact ITSELF, not a copy of it. A silent revision
# bump would move the gate under us.
BGE_M3_REPO = "BAAI/bge-m3"
BGE_M3_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
BGE_M3_TOKENIZER_SHA256 = "21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08"
PARSER_VERSION = "t9-18.3fix"  # provenance on every chunk (fix: затв. number now in the citation)


def load_tokenizer():
    """Pinned BGE-M3 tokenizer (XLM-RoBERTa SentencePiece, vocab 250 002). Zero cost, local
    after the first fetch. Raises if the artefact is not byte-identical to the pin."""
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer
    path = hf_hub_download(BGE_M3_REPO, "tokenizer.json", revision=BGE_M3_REVISION)
    got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if got != BGE_M3_TOKENIZER_SHA256:
        raise SystemExit(
            f"tokenizer.json sha256 mismatch — the 8192 gate would silently move.\n"
            f"  expected {BGE_M3_TOKENIZER_SHA256}\n  got      {got}\n  file {path}")
    return Tokenizer.from_file(path)


# ── canonical nreg (chunk layer ONLY) ────────────────────────────────────────────────
def canonical_map(conn) -> dict[str, str]:
    """{native nreg: canonical nreg} for the chunk layer — 3633-IX -> 3633-20.

    Sourced from the SAME map the freshness probe already maintains (`seed_alias_map`):
    one writer per fact. A second hand-kept alias list here is exactly the two-heads drift
    that invariant forbids. Acts with no alias map to themselves.
    """
    from pipelines.freshness.probe import seed_alias_map
    return seed_alias_map(conn)     # {'3633-IX': '3633-20', '3543-12': '3543-12', …}


# ── citation rendering ───────────────────────────────────────────────────────────────
# Derived ONLY from the canonical unit_path — never from the text.
# ⚠ «п.» means two different things depending on the parent: under a
# СТАТТЯ the «N.» level is a ЧАСТИНА («ст. 23 ч. 1»), under a розділ/додаток it is a ПУНКТ.
# Evidence: 3543-12 ст.23/п.1 reads «1. Не підлягають призову … 1) заброньовані …» and
# 560-2024-п's Додаток 5 cites that very unit as «1. Частина перша статті 23 Закону».
_SEG_RE = re.compile(r"^(розд|гл|ст|п|дод|затв)\.(.+)$")
_SEG_LABEL = {"розд": "розд.", "гл": "гл.", "ст": "ст.", "дод": "додаток ", "затв": ""}


def render_citation(unit_path: str, edition_date, kind: str, block_title: str | None = None) -> str:
    """«ст. 23 ч. 1 · ред. від 12.04.2026» — the string a chunk is cited by."""
    parts: list[str] = []
    segs = unit_path.split("/")
    for i, seg in enumerate(segs):
        if seg == "преамбула":
            parts.append("преамбула")
            continue
        if seg == "додаток":
            parts.append("додаток")
            continue
        m = _SEG_RE.match(seg)
        if not m:
            parts.append(seg)
            continue
        tag, num = m.group(1), m.group(2)
        if tag == "п":
            parent_tag = _SEG_RE.match(segs[i - 1]).group(1) if i and _SEG_RE.match(segs[i - 1]) \
                else ("преамбула" if i and segs[i - 1] == "преамбула" else None)
            # under a стаття the numbered level is a ЧАСТИНА, everywhere else a ПУНКТ
            parts.append(f"ч. {num}" if parent_tag == "ст" else f"п. {num}")
        elif tag == "затв":
            # The block ORDINAL is load-bearing, not decoration: 560-2024-п titles BOTH затв.1 and
            # затв.2 «ПОРЯДОК» (76-2023-п likewise), so dropping `num` gave two different chunks one
            # citation — 23 strings over 46 chunks (a defect caught in review). Always rendered,
            # even for a lone block (z1109-08 затв.1): a form that appears only on collision is a
            # form nobody can cite against.
            parts.append(f"{block_title} (затв. {num})" if block_title else f"затв. {num}")
        else:
            parts.append(f"{_SEG_LABEL[tag]}{num}".replace(".", ". ", 1)
                         if tag != "дод" else f"додаток {num}")
    return f"{' '.join(parts)} · ред. від {edition_date.strftime('%d.%m.%Y')}"


# ── build ────────────────────────────────────────────────────────────────────────────
def _perimeter_units(conn):
    """Every unit of the CURRENT in-force edition of each perimeter act, with its title and
    whether it has children (an oversize unit is represented by its children)."""
    with conn.cursor() as cur:
        cur.execute(f"""
            WITH latest AS (
                SELECT act_nreg, max(edition_date) AS ed FROM units
                WHERE act_nreg = ANY(%s)
                  AND edition_date <= (now() AT TIME ZONE '{KYIV}')::date
                GROUP BY 1)
            SELECT u.act_nreg, u.edition_date, u.unit_path, u.kind, u.title, u.text, u.char_len,
                   EXISTS (SELECT 1 FROM units k
                           WHERE k.act_nreg = u.act_nreg AND k.edition_date = u.edition_date
                             AND k.unit_path LIKE u.unit_path || '/%%') AS has_kids
            FROM units u JOIN latest l ON l.act_nreg = u.act_nreg AND l.ed = u.edition_date
            ORDER BY u.act_nreg, u.ordinal""", (list(PERIMETER),))
        return cur.fetchall()


def eligible(kind: str, char_len: int, text: str, title: str | None) -> bool:
    """Chunk-eligible: has its own text, and is not a bare heading.

    NULL-safe by construction (a review finding): `NOT (text = title)` evaluates to NULL for the
    3 288 point units whose title IS NULL, silently dropping every one of them (denominator
    1 325 instead of 4 613). `IS DISTINCT FROM` is the only correct form.
    """
    return char_len > 0 and (text is not None and text != title)


def build(conn, tok) -> dict:
    rows = _perimeter_units(conn)
    aliases = canonical_map(conn)
    canon = {a: aliases.get(a, a) for a in {r[0] for r in rows}}
    titles = {(r[0], r[2]): r[4] for r in rows}
    with conn.cursor() as cur:
        cur.execute("SELECT nreg, title FROM acts")
        act_titles = dict(cur.fetchall())

    kept, oversize_parent, hard_fail, skipped = [], [], [], 0
    for act, ed, path, kind, title, text, char_len, has_kids in rows:
        if not eligible(kind, char_len, text, title):
            skipped += 1
            continue
        n_tok = len(tok.encode(text).ids)
        if n_tok > WINDOW:
            (oversize_parent if has_kids else hard_fail).append((act, path, char_len, n_tok))
            continue
        block_title = titles.get((act, path.split("/")[0])) if path.startswith("затв.") else None
        kept.append((canon[act], path, ed, act, kind, text, char_len, n_tok,
                     render_citation(path, ed, kind, block_title), act_titles.get(act),
                     ed, None, PARSER_VERSION))

    with conn.cursor() as cur:
        cur.execute("DELETE FROM chunks WHERE src_act_nreg = ANY(%s)", (list(PERIMETER),))
        cur.executemany(
            "INSERT INTO chunks (act_nreg, unit_path, edition_date, src_act_nreg, kind, text,"
            " char_len, n_tokens, citation, act_title, in_force_from, in_force_to,"
            " parser_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", kept)
    conn.commit()
    return {"units": len(rows), "skipped_ineligible": skipped, "chunks": len(kept),
            "oversize_with_children": oversize_parent, "hard_fail_leaves": hard_fail}


# ── verify ───────────────────────────────────────────────────────────────────────────
def verify(conn) -> dict:
    """Every chunk must resolve back to a real unit, and nothing may exceed the window."""
    out = {}
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks")
        out["chunks"] = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM chunks c WHERE NOT EXISTS (
                         SELECT 1 FROM units u WHERE u.act_nreg = c.src_act_nreg
                           AND u.edition_date = c.edition_date AND u.unit_path = c.unit_path)""")
        out["unresolvable"] = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM chunks c JOIN units u
                         ON u.act_nreg = c.src_act_nreg AND u.edition_date = c.edition_date
                        AND u.unit_path = c.unit_path
                       WHERE u.text IS DISTINCT FROM c.text""")
        out["text_drift"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM chunks WHERE n_tokens > %s", (WINDOW,))
        out["over_window"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM chunks WHERE citation IS NULL OR citation = ''")
        out["no_citation"] = cur.fetchone()[0]
        # Citation UNIQUENESS inside (act_nreg, edition_date) — a defect caught in review.
        # A citation naming two atom_id's is a hole under the structural citation gate: it can
        # verify that a cited id EXISTS, not that the string resolves to the chunk actually served.
        # Counts colliding STRINGS (groups), not the chunks in them — 23 vs 46 before the fix.
        cur.execute("""SELECT count(*) FROM (SELECT act_nreg, edition_date, citation FROM chunks
                       GROUP BY 1, 2, 3 HAVING count(*) > 1) x""")
        out["citation_collisions"] = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM chunks WHERE edition_date > "
                    f"(now() AT TIME ZONE '{KYIV}')::date")
        out["future_chunks"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM chunks WHERE act_nreg = '3633-IX'")
        out["uncanonical_nreg"] = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT act_nreg) FROM chunks")
        out["acts"] = cur.fetchone()[0]
    return out


def sample(conn, n: int, seed: int) -> list:
    """Fixed-seed acceptance sample — reproducible, quoted in the write-up."""
    with conn.cursor() as cur:
        cur.execute("SELECT act_nreg, unit_path, edition_date, kind, n_tokens, char_len, "
                    "citation, text FROM chunks ORDER BY act_nreg, unit_path")
        rows = cur.fetchall()
    return random.Random(seed).sample(rows, min(n, len(rows)))


def main() -> int:
    ap = argparse.ArgumentParser(description="T9 chunker: units -> citable chunks")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=20260716)
    args = ap.parse_args()

    if args.build:
        # loud unless orchestrated — but ONLY for --build, the one mode that WRITES and
        # is journaled as A-03c. `--verify`/`--sample` are read-only diagnostics; warning on them
        # would cry wolf at every debug run and train the operator to ignore the warning.
        from pipelines.orchestration import warn_if_standalone
        warn_if_standalone("A-03c (rada.chunk --build)")

    with connect() as conn:
        if args.build:
            built = 0
            try:
                # A pin mismatch raises SystemExit (BaseException) — deliberately NOT caught here:
                # nothing was built, so there is nothing to measure, and the message must reach
                # stderr → run_one's ingest_errors. Refusing to build is the honest red run.
                tok = load_tokenizer()
                print(f"tokenizer pinned: {BGE_M3_REPO}@{BGE_M3_REVISION[:12]} "
                      f"sha256={BGE_M3_TOKENIZER_SHA256[:16]}… vocab={tok.get_vocab_size()}")
                r = build(conn, tok)
                built = r["chunks"]
                print(f"perimeter units={r['units']}  ineligible(skipped)={r['skipped_ineligible']}"
                      f"  -> chunks={r['chunks']}")
                print(f"\noversize > {WINDOW} tokens, represented by children: "
                      f"{len(r['oversize_with_children'])}")
                for a, p, c, t in r["oversize_with_children"]:
                    print(f"   {a:12s} {p:28s} chars={c:7d} tokens={t:6d}")
                print(f"\nHARD-FAIL — oversize LEAVES (no children to decompose into): "
                      f"{len(r['hard_fail_leaves'])}")
                for a, p, c, t in r["hard_fail_leaves"]:
                    print(f"   !! {a:12s} {p:28s} chars={c:7d} tokens={t:6d}")
                # Modelled on parse_structure's "DONE: parsed …": run_one journals the LAST
                # non-summary stdout line as the run's note. Without this the note would be the
                # last hard-fail leaf ("!! z1109-08 …") — an 'ok' run whose journal line reads
                # like a crash.
                print(f"\nDONE: built {r['chunks']} chunks from {r['units']} perimeter units "
                      f"({r['skipped_ineligible']} ineligible, {len(r['oversize_with_children'])} "
                      f"oversize→children, {len(r['hard_fail_leaves'])} oversize leaves not represented).")
            except Exception:
                # Modelled on parse_structure: even a mid-build crash emits an HONEST summary
                # (partial ok + failed=1) so the orchestrator journals real counts, not
                # 'unmeasured'; then re-raise so the subprocess still exits non-zero.
                _summary.emit(ok=built, failed=1, nbytes=0)
                raise
            # Honest counts for the orchestrator. Derived transform — no wire bytes.
            # failed=0 DELIBERATELY, though 5 oversize leaves could not be represented (decided
            # 2026-07-16). `failed` means a TRANSIENT shortfall — something a re-run could fix
            # (the court-text fetch errors are the type). The 5 leaves are a PERMANENT structural
            # property of the corpus, accepted by design: emitting them every single day would
            # train the eye to ignore items_failed, and a real shortfall is already caught by the
            # floor + the must-be-0 probes. They stay visible where they belong — the DONE
            # line/note above and the known-limitations list — not in a counter meant to mean
            # "something broke".
            _summary.emit(ok=r["chunks"], failed=0, nbytes=0)
        if args.verify:
            for k, v in verify(conn).items():
                print(f"{k:22s} {v}")
        if args.sample:
            for i, (act, path, ed, kind, ntok, clen, cit, text) in enumerate(
                    sample(conn, args.sample, args.seed), 1):
                body = " / ".join(text.split("\n"))[:200]
                print(f"\n--- {i}. atom_id = ({act}, {path}, {ed})")
                print(f"    kind={kind}  tokens={ntok}  chars={clen}")
                print(f"    citation: {cit}")
                print(f"    text[:200]: {body}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
