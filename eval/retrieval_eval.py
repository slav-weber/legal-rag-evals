"""Retrieval eval: recall@k across the layered pipeline (dense → RRF → rerank).

Measures whether the expected article is among the top-k retrieved candidates, BY ARTICLE (a hit
is any chunk `ст.N` or `ст.N/*` of the expected act). `--mode` picks the stage, so the lift of each
layer can be read directly:
  dense  — bi-encoder baseline (layer 1)
  hybrid — RRF fusion of dense + FTS + lemma (layer 4)      [recall: get the target into the top-N]
  rerank — hybrid → cross-encoder reorder (layer 5, full)   [precision: put it at the top]
  all    — run all three and print the recall@k lift table (default)

The acceptance number over the `questions_v0` set comes only AFTER its gold markup is written; that
gold is empty by design, because an eval must not grade itself. Until then this runs on the
committed smoke set (`eval/data/smoke_retrieval.jsonl`, 5 gold questions) to prove the harness and
the pipeline work end to end — the smoke set is PARAPHRASES, where dense retrieval is already at
its ceiling, so the RRF / rerank lift shows up on the distinctive-term and citation-lookup gold,
not here.

LIVE ONLY — it embeds the query with the real BGE-M3 and reranks with the real
bge-reranker-v2-m3: acceptance never mocks embeddings or the reranker.

    uv run python eval/retrieval_eval.py                       # smoke gold, all modes, k=10
    uv run python eval/retrieval_eval.py --mode rerank --k 10
    uv run python eval/retrieval_eval.py --gold <file> --mode all
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.rag import retrieval  # noqa: E402

SMOKE = Path(__file__).resolve().parent / "data" / "smoke_retrieval.jsonl"

# Canonical gold format: 'act_nreg ст.N' — the citation is pinned at the article (ст.N) level;
# частини and пункти below it match by prefix in _gold_rank. NOT an atom_id, NOT a structural
# object.
_ARTICLE_RE = re.compile(r"^ст\.\d+(-\d+)?$")


class GoldFormatError(ValueError):
    """A gold citation the harness cannot score. FAIL-LOUD: a malformed gold string must raise
    with its line number and NEVER become a silent MISS — a falsely failed recall count is worse
    than an error, because it would corrupt the calibration built on top of it."""


def _parse_citation(s: str, known_acts: set[str], lineno: int) -> tuple[str, str]:
    parts = str(s).split()
    if len(parts) < 2:
        raise GoldFormatError(f"gold line {lineno}: '{s}' — need 'act_nreg ст.N' (≥2 tokens)")
    act, art = parts[0], parts[1]
    if act not in known_acts:
        raise GoldFormatError(f"gold line {lineno}: unknown act_nreg '{act}' in '{s}' "
                              f"(canonical nreg expected, e.g. 3633-20 not 3633-IX)")
    if not _ARTICLE_RE.match(art):
        raise GoldFormatError(f"gold line {lineno}: '{art}' in '{s}' is not ст.N form — an atom_id "
                              f"or a structural object is not accepted (частини match by prefix)")
    return act, art


def _load_gold(path: Path, known_acts: set[str]) -> list[dict]:
    """Normalise each row to {question, as_of, expected:[(act, article)]}, VALIDATING every gold
    citation (fail-loud on a malformed one). Supports the smoke format (expected_act /
    expected_article) and the questions_v0 format (gold_citations, 'act_nreg ст.N'). A row with NO
    gold at all is kept with expected=[] (unmarked → skipped by main, not an error)."""
    out = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        expected: list[tuple[str, str]] = []
        if r.get("expected_act") or r.get("expected_article"):   # smoke format — validate too
            expected.append(_parse_citation(f"{r.get('expected_act','')} "
                                            f"{r.get('expected_article','')}", known_acts, lineno))
        for g in r.get("gold_citations", []):                    # questions_v0 gold
            expected.append(_parse_citation(g, known_acts, lineno))
        # Carry gold_key_points + theme so the generation harness REUSES this one fail-loud
        # validator instead of growing a second one — and VALIDATE them here (fail-loud, not
        # passthrough, before the harness consumes them). retrieval_eval itself ignores the fields.
        kps = r.get("gold_key_points", [])
        if not isinstance(kps, list) or any(not isinstance(k, str) for k in kps):
            raise GoldFormatError(f"gold line {lineno}: gold_key_points must be a list of strings")
        theme = r.get("theme")
        if theme is not None and not isinstance(theme, str):
            raise GoldFormatError(f"gold line {lineno}: theme must be a string (or absent)")
        out.append({"id": r.get("id"), "question": r["question"], "class": r.get("class", "all"),
                    "as_of": r.get("as_of_date"), "expected": expected, "key_points": kps,
                    "theme": theme})
    return out


def _known_acts(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT act_nreg FROM chunks")
        return {r[0] for r in cur.fetchall()}


def _gold_rank(top: list[dict], expected: list[tuple[str, str]]) -> int | None:
    """1-based rank of the FIRST hit by article (the ст.N chunk itself OR any частина under it),
    else None. Drives recall@k (rank ≤ k), precision@1 (rank == 1) and MRR@k (1/rank)."""
    for i, h in enumerate(top, 1):
        if any(h["act"] == act and (h["unit_path"] == art or h["unit_path"].startswith(art + "/"))
               for act, art in expected):
            return i
    return None


MODES = ("dense", "hybrid", "rerank")


def _retrieve(conn, mode: str, question: str, as_of, k: int) -> tuple[list[dict], dict]:
    """One stage of the layered pipeline → (top-k hits, meta). dense returns no meta (layer 1);
    rerank is the FULL pipeline (exact lookup → hybrid → rerank, layer 5 plus the exact route)."""
    if mode == "dense":
        return retrieval.dense(conn, question, as_of=as_of, k=k), {}
    if mode == "hybrid":
        return retrieval.hybrid(conn, question, as_of=as_of, k=k)
    if mode == "rerank":
        return retrieval.search(conn, question, as_of=as_of, k=k)
    raise ValueError(f"unknown mode {mode!r}")


def _run_mode(conn, mode: str, gold: list[dict], k: int) -> dict:
    """Score one mode over the gold, BROKEN DOWN BY CLASS: recall@k / p@1 / MRR@k per class and
    overall. Returns {class: {n, recall, p1, mrr}} for the cross-mode table in main()."""
    from collections import defaultdict
    stats: dict = defaultdict(lambda: {"n": 0, "recall": 0, "p1": 0, "mrr": 0.0})
    misses: list[tuple] = []
    for g in gold:
        top, _meta = _retrieve(conn, mode, g["question"], g["as_of"], k)
        rank = _gold_rank(top, g["expected"])
        s = stats[g["class"]]
        s["n"] += 1
        if rank is not None:
            s["recall"] += 1
            s["p1"] += (rank == 1)
            s["mrr"] += 1.0 / rank
        else:
            misses.append((g["id"], g["class"]))
    print(f"--- mode={mode} ---")
    for cls in sorted(stats):
        s = stats[cls]
        print(f"  {cls:12s} n={s['n']:2d}  recall@{k}={s['recall']/s['n']:.3f}  "
              f"p@1={s['p1']/s['n']:.3f}  MRR@{k}={s['mrr']/s['n']:.3f}")
    if misses:
        print(f"  misses (outside top-{k}): {', '.join(f'id{i}({c})' for i, c in misses)}")
    print()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Retrieval eval: recall@k (dense → RRF → rerank)")
    ap.add_argument("--gold", default=str(SMOKE))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--mode", choices=[*MODES, "all"], default="all",
                    help="which pipeline stage to score (all = lift table)")
    args = ap.parse_args()

    from ml.embed_index import _lm_up, _model
    from pipelines.db import connect
    modes = MODES if args.mode == "all" else (args.mode,)
    with connect() as conn:
        known = _known_acts(conn)
        # Gold validation is a STATIC check (no LM) — run it FIRST so a malformed gold file fails
        # loud (exit 2) REGARDLESS of LM Studio: failing loud on bad gold must not depend on the
        # model being up. The LM check follows, gating only the actual retrieval.
        try:
            rows = _load_gold(Path(args.gold), known)     # fail-loud on malformed gold
        except GoldFormatError as exc:
            print(f"!! GOLD FORMAT ERROR — {exc}")
            return 2
        gold = [g for g in rows if g["expected"]]
        if not gold:
            print(f"!! no scorable gold in {args.gold} ({len(rows)} rows, gold_citations empty "
                  f"— awaiting the gold markup).")
            return 1
        if not _lm_up():
            print("!! LM Studio unreachable — retrieval embeds the query live (embeddings are "
                  "never mocked). Action required: start LM Studio with BGE-M3.")
            return 1

        print(f"retrieval eval: {len(gold)}/{len(rows)} scorable, k={args.k}, model {_model()}, "
              f"gold {args.gold}\n")
        results = {mode: _run_mode(conn, mode, gold, args.k) for mode in modes}

    if len(modes) > 1:
        classes = sorted({c for r in results.values() for c in r})
        print(f"=== lift by class (recall@{args.k} / p@1 / MRR@{args.k}) ===")
        for cls in classes:
            for mode in modes:
                s = results[mode].get(cls)
                if s:
                    print(f"  {cls:12s} {mode:8s} n={s['n']:2d}  recall={s['recall']/s['n']:.3f}  "
                          f"p@1={s['p1']/s['n']:.3f}  MRR={s['mrr']/s['n']:.3f}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
