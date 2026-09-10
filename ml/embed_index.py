"""Build the BGE-M3 passage-embedding index over chunks_indexable (pipeline step A-03d).

Reads `chunks_indexable`, writes ONLY `embeddings`.

Lifecycle: embeddings are keyed by CONTENT, not atom_id — PK (model, text_hash) where
text_hash = chunks.content_hash = sha256(raw text). The daily A-03c DELETE+INSERT of chunks does
NOT touch this cache (no FK), and a bit-identical rebuild reuses every embedding (same hashes) ⇒
0 re-embeddings on a quiet day. Only genuinely-changed text (new hash) is embedded.

Model pin: the model name + dim(1024) live in the env; a committed reference vector
(ml/embeddings_reference.json) is re-embedded every build and compared by cosine ≥ 0.9999 — a
silent model swap on the same :1234 endpoint drifts below the threshold → red (SystemExit), never
a fallback. LM Studio unavailable = honest exit, never a substitute model. (R-10 is the project's
fail-honestly rule: a missing dependency is reported loudly and never silently substituted.)

Run:
  uv run python -m ml.embed_index --build           # embed missing hashes (near-no-op on a quiet day)
  uv run python -m ml.embed_index --gen-reference    # FIRST live run: write the reference (commit it)
  uv run python -m ml.embed_index --coverage         # report indexable coverage, no writes
"""

from __future__ import annotations

import argparse
import json
import math
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
PASSAGE_PREFIX = "passage: "     # ONLY passage vectors are cached (query: is ephemeral, retrieval-side)
QUERY_PREFIX = "query: "         # used at retrieval time, never stored
DIM = 1024                       # schema-critical (embeddings CHECK dim=1024)
COSINE_THRESHOLD = 0.9999        # reference drift below this = model swap = red
BATCH = 64                       # embed+commit per batch → checkpoint = the content-hash cache

# fixed canonical string — hero-vocabulary so a wrong model drifts hard, not marginally.
REF_STRING = "контрольний рядок BGE-M3 · оборона, мобілізація, відстрочка, стаття 23"
REFERENCE_PATH = Path(__file__).resolve().parent / "embeddings_reference.json"

_LM_DOWN_HINT = ("nothing can embed the new content — start LM Studio with BGE-M3 (the only "
                 "model on disk, mandatory). This is an honest R-10 exit, NOT a fallback.")


def _model() -> str:
    from ml.llm_client import DEFAULT_EMBEDDINGS_MODEL
    if not DEFAULT_EMBEDDINGS_MODEL:
        raise SystemExit("EMBEDDINGS_MODEL not set in .env — the model pin is empty.")
    return DEFAULT_EMBEDDINGS_MODEL


def _lm_up() -> bool:
    from ml.llm_client import list_models
    try:
        return _model() in list_models()
    except Exception:  # noqa: BLE001 — APIConnectionError etc. → down
        return False


def _l2(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec))
    if n == 0:
        raise ValueError("zero-norm embedding — model returned a null vector")
    return [x / n for x in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))   # both are L2-normalised → dot = cosine


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Embed with the 'passage: ' prefix, L2-normalised. Raises on a wrong dim (schema-critical)."""
    from ml.llm_client import embed
    raw = embed([PASSAGE_PREFIX + t for t in texts], model=_model())
    out = []
    for v in raw:
        if len(v) != DIM:
            raise SystemExit(f"model returned dim {len(v)}, expected {DIM} — schema-critical pin "
                             f"(embeddings.vector({DIM})). Wrong model loaded in LM Studio?")
        out.append(_l2(v))
    return out


def embed_query(text: str) -> list[list[float]]:
    """'query: '-prefixed, L2-normalised — for retrieval / smoke. EPHEMERAL, never stored."""
    from ml.llm_client import embed
    return [_l2(v) for v in embed([QUERY_PREFIX + text], model=_model())]


def check_pin() -> str:
    """Re-embed the reference string and compare to the committed vector (cosine ≥ threshold).
    First live run (no reference file) BOOTSTRAPS it. Drift → SystemExit (not a fallback).
    Returns a human status line."""
    model = _model()
    live = embed_passages([REF_STRING])[0]
    if not REFERENCE_PATH.exists():
        REFERENCE_PATH.write_text(json.dumps(
            {"model": model, "prefix": PASSAGE_PREFIX, "dim": DIM, "text": REF_STRING,
             "cosine_threshold": COSINE_THRESHOLD, "vector": live}, ensure_ascii=False), encoding="utf-8")
        return (f"reference BOOTSTRAPPED → {REFERENCE_PATH.name} (model {model}) — COMMIT it "
                f"(the reference is generated by the first live run)")
    ref = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    if ref["model"] != model:
        raise SystemExit(f"model pin drift: reference is '{ref['model']}', .env has '{model}'.")
    cos = _cosine(live, ref["vector"])
    if cos < ref.get("cosine_threshold", COSINE_THRESHOLD):
        raise SystemExit(f"MODEL DRIFT: reference cosine {cos:.6f} < {ref['cosine_threshold']} — "
                         f"LM Studio serves a DIFFERENT model on :1234 than '{model}'. Refusing "
                         f"to embed against an unpinned model. Not a fallback.")
    return f"pin OK: reference cosine {cos:.6f} ≥ {ref['cosine_threshold']} (model {model})"


def missing_hashes(conn, model: str) -> list[tuple[str, str]]:
    """(content_hash, text) for every indexable chunk whose (model, hash) is not yet embedded.
    DISTINCT by hash — identical-text chunks share one embedding (content-hash keying)."""
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT ci.content_hash, ci.text FROM chunks_indexable ci
                       WHERE NOT EXISTS (SELECT 1 FROM embeddings e
                                         WHERE e.model = %s AND e.text_hash = ci.content_hash)""",
                    (model,))
        return cur.fetchall()


def coverage_gap(conn, model: str) -> tuple[int, int]:
    """(missing, total) indexable hashes for `model`. Used by A-03d's validator (_v_a03d)."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(DISTINCT content_hash) FROM chunks_indexable")
        total = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM (SELECT DISTINCT ci.content_hash FROM chunks_indexable ci
                       WHERE NOT EXISTS (SELECT 1 FROM embeddings e
                       WHERE e.model = %s AND e.text_hash = ci.content_hash)) x""", (model,))
        return cur.fetchone()[0], total


def build(conn) -> dict:
    """Embed every missing indexable hash, batch+commit. LM down + missing = honest R-10 exit."""
    model = _model()
    missing = missing_hashes(conn, model)
    if not missing:
        return {"model": model, "embedded": 0, "missing": 0, "note": "coverage already complete"}
    if not _lm_up():
        # new content exists but the model is unreachable — the ONLY case that must fail loudly.
        return {"model": model, "embedded": 0, "missing": len(missing), "lm_down": True}

    pin = check_pin()   # drift → SystemExit; first run bootstraps the reference
    print(f"  {pin}")
    embedded = 0
    for i in range(0, len(missing), BATCH):
        chunk = missing[i:i + BATCH]
        vecs = embed_passages([t for _h, t in chunk])
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO embeddings (model, text_hash, dim, embedding) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (model, text_hash) DO NOTHING",
                [(model, h, DIM, str(v)) for (h, _t), v in zip(chunk, vecs)])
        conn.commit()   # checkpoint per batch — resume = re-query missing hashes (idempotent)
        embedded += len(chunk)
        print(f"  embedded {embedded}/{len(missing)}")
    return {"model": model, "embedded": embedded, "missing": 0}


def main() -> int:
    ap = argparse.ArgumentParser(description="A-03d: build BGE-M3 passage embeddings")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--gen-reference", action="store_true",
                    help="write embeddings_reference.json (first live run)")
    ap.add_argument("--coverage", action="store_true")
    args = ap.parse_args()

    if args.build:
        from pipelines.orchestration import warn_if_standalone
        warn_if_standalone("A-03d (ml.embed_index --build)")

    with connect() as conn:
        if args.gen_reference:
            if REFERENCE_PATH.exists():
                print(f"{REFERENCE_PATH.name} already exists — delete it to regenerate")
                return 0
            print(check_pin())        # bootstraps + writes
            return 0
        if args.coverage:
            model = _model()
            gap, total = coverage_gap(conn, model)
            print(f"indexable hashes {total} · embedded {total - gap} · missing {gap} · model {model}")
            return 0
        if args.build:
            r = build(conn)
            if r.get("lm_down"):
                # honest R-10 exit: content to embed but LM Studio down. items_failed = the gap.
                print(f"\n!! A-03d BLOCKED — {r['missing']} indexable hash(es) unembedded and "
                      f"LM Studio unreachable.\n   needs_from_human: {_LM_DOWN_HINT}")
                _summary.emit(ok=0, failed=r["missing"], nbytes=0)
                return 1
            print(f"\nDONE: embedded {r['embedded']} passage-vector(s) "
                  f"({r['note'] if r.get('note') else 'model ' + r['model']}); missing now {r['missing']}.")
            _summary.emit(ok=r["embedded"], failed=0, nbytes=0)
            return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
