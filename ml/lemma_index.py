"""Build the Ukrainian lemma index over chunks_indexable (pipeline step A-03e).

Reads `chunks_indexable`, writes ONLY `lemma_cache`.
v0 = MORPHOLOGY ONLY: lemmatize word forms so «відстрочку»↔«відстрочка» match, which `simple`-FTS
misses (measured on the FTS channel: 1/5). Part B (normalising special tokens such as ст.283-2 /
nreg) is DEFERRED by plan: it lands as a REBUILD (bump TOKENIZER_VERSION → re-run A-03e), not as a
migration.

Lifecycle (mirror of embeddings): keyed by (content_hash, PIPELINE_VERSION), NO FK to
chunks ⇒ the daily A-03c DELETE+INSERT does NOT touch it; a bit-identical rebuild reuses every
entry (same hashes) ⇒ 0 re-lemmatisations on a quiet day. PIPELINE_VERSION = dict + tokenizer
version: changing EITHER forces a clean rebuild (the pin).

    uv run python -m ml.lemma_index --build       # lemmatize missing hashes (near-no-op quiet day)
    uv run python -m ml.lemma_index --coverage     # report coverage, no writes
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines import summary as _summary  # noqa: E402
from pipelines.db import connect  # noqa: E402

# ── pin ───────────────────────────────────────────────────────────────────────────────
# Both halves keyed into lemma_cache: a change to EITHER forces a full rebuild via the PK.
DICT_VERSION = "uk-2.4.1.1.1663094765"   # pymorphy3-dicts-uk (pinned in pyproject)
TOKENIZER_VERSION = "w1"                  # word tokenizer v1 (morphology-only); bump when part B lands
PIPELINE_VERSION = f"{DICT_VERSION}+tok-{TOKENIZER_VERSION}"
BATCH = 500

# v0 tokenizer (morphology-only): Unicode word runs. Splits dashed special tokens (283-2 → 283,2)
# — acceptable for v0 (part B, which preserves them, is deferred).
_WORD = re.compile(r"\w+", re.UNICODE)
_analyzer = None


def _morph():
    global _analyzer
    if _analyzer is None:
        import pymorphy3
        _analyzer = pymorphy3.MorphAnalyzer(lang="uk")   # uk-only; dicts-ru transitive, unused
    return _analyzer


def lemmatize(text: str) -> str:
    """Space-joined lemmas of the word tokens — the SAME function indexes a chunk and processes a
    query (one writer: index and query are lemmatised identically, otherwise a match cannot line
    up)."""
    m = _morph()
    return " ".join(m.parse(w)[0].normal_form for w in _WORD.findall(text.lower()))


def missing_hashes(conn) -> list[tuple[str, str]]:
    """(content_hash, text) for every indexable chunk with no (content_hash, PIPELINE_VERSION) row.
    DISTINCT by hash — identical-text chunks share one lemma entry (content-hash keying)."""
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT ci.content_hash, ci.text FROM chunks_indexable ci
                       WHERE NOT EXISTS (SELECT 1 FROM lemma_cache l
                                         WHERE l.content_hash = ci.content_hash
                                           AND l.pipeline_version = %s)""", (PIPELINE_VERSION,))
        return cur.fetchall()


def coverage_gap(conn) -> tuple[int, int]:
    """(missing, total) indexable hashes for the CURRENT pipeline. Used by _v_a03e."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(DISTINCT content_hash) FROM chunks_indexable")
        total = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM (SELECT DISTINCT ci.content_hash FROM chunks_indexable ci
                       WHERE NOT EXISTS (SELECT 1 FROM lemma_cache l WHERE l.content_hash = ci.content_hash
                       AND l.pipeline_version = %s)) x""", (PIPELINE_VERSION,))
        return cur.fetchone()[0], total


def build(conn) -> dict:
    """Lemmatize every missing indexable hash, batch+commit. Pure Python+DB — no LM Studio."""
    missing = missing_hashes(conn)
    if not missing:
        return {"lemmatized": 0, "missing": 0, "note": "coverage already complete"}
    done = 0
    for i in range(0, len(missing), BATCH):
        batch = missing[i:i + BATCH]
        rows = [(h, PIPELINE_VERSION, lemmatize(t)) for h, t in batch]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO lemma_cache (content_hash, pipeline_version, lemma_tsv) "
                "VALUES (%s, %s, to_tsvector('simple', %s)) ON CONFLICT DO NOTHING", rows)
        conn.commit()   # checkpoint per batch — resume = re-query missing hashes (idempotent)
        done += len(batch)
        print(f"  lemmatized {done}/{len(missing)}")
    return {"lemmatized": done, "missing": 0}


def main() -> int:
    ap = argparse.ArgumentParser(description="A-03e: build Ukrainian lemma index")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    args = ap.parse_args()

    if args.build:
        from pipelines.orchestration import warn_if_standalone
        warn_if_standalone("A-03e (ml.lemma_index --build)")

    with connect() as conn:
        if args.coverage:
            gap, total = coverage_gap(conn)
            print(f"indexable hashes {total} · lemmatized {total - gap} · missing {gap} · "
                  f"pipeline {PIPELINE_VERSION}")
            return 0
        if args.build:
            try:
                r = build(conn)
            except Exception:
                _summary.emit(ok=0, failed=1, nbytes=0)
                raise
            print(f"\nDONE: lemmatized {r['lemmatized']} chunk(s) "
                  f"({r.get('note') or 'pipeline ' + PIPELINE_VERSION}); missing now {r['missing']}.")
            _summary.emit(ok=r["lemmatized"], failed=0, nbytes=0)
            return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
