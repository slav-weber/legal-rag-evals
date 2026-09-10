"""Freeze a RETRIEVAL baseline: top-k per gold question, hashed, persisted.

Why this exists (2026-07-19). The corpus is about to grow (today: 4 706 chunks from
14 acts, while the national legal-acts registry knows 143 251 acts). Growing it perturbs the
candidate pool: RRF ranks shift and the cross-encoder re-orders, so a question that is
answered correctly today can silently lose its gold norm out of top-k — on a THEME nobody
was touching. A "we did not break anything" claim is only worth the measurement that
precedes the change, so this takes the BEFORE snapshot.

Retrieval-only by design: no DeepSeek call, no generation. That keeps the run free, fast
and deterministic enough to be a regression instrument — generation noise (measured: 0.310
set-flip at temp=0) would drown the signal we are trying to see.

    uv run python -m eval.retrieval_baseline --out eval/baselines/retrieval_<tag>.jsonl
    uv run python -m eval.retrieval_baseline --compare eval/baselines/retrieval_<tag>.jsonl

Compare reports, per question and per class: gold kept/lost in top-k (the RED signal),
rank of the gold hit, and set churn (informational — reordering is expected and is not by
itself a regression).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from eval.retrieval_eval import _known_acts, _load_gold  # noqa: E402  the ONE gold validator
from pipelines.db import connect                         # noqa: E402
from pipelines.rag.retrieval import search               # noqa: E402

DEFAULT_GOLD = REPO / "eval" / "data" / "retrieval_gold_v0.jsonl"
TOP_K = 10                                               # = GEN_K: what generation actually sees


def _stem(citation: str) -> str:
    """'ст. 23 ч. 9' → 'ст.23' — gold is per article, chunks may be leaf-grained."""
    head = citation.split("·")[0].strip()
    parts = head.replace("ст.", "ст. ").split()
    for i, p in enumerate(parts):
        if p.startswith("ст") and i + 1 < len(parts):
            return "ст." + parts[i + 1].rstrip(".,")
    return head


def probe(conn, question: str, as_of=None, k: int = TOP_K) -> tuple[list[dict], dict]:
    hits, meta = search(conn, question, as_of=as_of, k=k)
    rows = [{"rank": i, "act": h["act"], "citation": h.get("citation", ""),
             "stem": _stem(h.get("citation", ""))} for i, h in enumerate(hits, 1)]
    return rows, meta


def capture(gold_path: Path, out_path: Path, k: int = TOP_K) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kept = 0
    with connect() as conn, open(out_path, "w", encoding="utf-8") as fh:
        gold = _load_gold(gold_path, _known_acts(conn))
        header = {"kind": "retrieval-baseline", "t": datetime.now(timezone.utc).isoformat(),
                  "gold": str(gold_path.relative_to(REPO)), "n": len(gold), "k": k,
                  "corpus": _corpus_shape(conn)}
        fh.write(json.dumps(header, ensure_ascii=False) + "\n")
        for row in gold:
            hits, meta = probe(conn, row["question"], row.get("as_of"), k)
            want = {(a, u) for a, u in row["expected"]}
            hit_rank = next((h["rank"] for h in hits if (h["act"], h["stem"]) in want), None)
            kept += 1 if hit_rank else 0
            fh.write(json.dumps({
                "id": row["id"], "class": row.get("class"),
                # the question is already committed gold — no user data here by construction
                "q_sha1": hashlib.sha1(row["question"].encode("utf-8")).hexdigest()[:12],
                "gold": sorted(f"{a} {u}" for a, u in want),
                "gold_rank": hit_rank, "route": meta.get("route"),
                "reranked": bool(meta.get("reranked")), "degraded": meta.get("degraded", []),
                "top": hits,
            }, ensure_ascii=False) + "\n")
    print(f"baseline: {kept}/{len(gold)} gold present in top-{k} → {out_path}")
    return {"n": len(gold), "kept": kept}


def _corpus_shape(conn) -> dict:
    """Pin WHAT the baseline was taken against — a baseline without its corpus is unreadable."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), count(DISTINCT act_nreg) FROM chunks")
        chunks, acts = cur.fetchone()
    return {"chunks": chunks, "acts": acts}


def _load(path: Path) -> tuple[dict, dict]:
    lines = [json.loads(line) for line in open(path, encoding="utf-8")]
    return lines[0], {r["id"]: r for r in lines[1:]}


def compare(base_path: Path, gold_path: Path, k: int = TOP_K) -> int:
    """Re-probe live and diff against the frozen baseline. Exit 1 on a LOST gold hit."""
    header, base = _load(base_path)
    lost, gained, moved, by_class = [], [], [], {}
    with connect() as conn:
        gold = {r["id"]: r for r in _load_gold(gold_path, _known_acts(conn))}
        now_shape = _corpus_shape(conn)
        for qid, b in base.items():
            row = gold.get(qid)
            if row is None:                              # gold row deleted → fail loud
                raise SystemExit(f"gold id {qid} missing from {gold_path} — baseline is stale")
            hits, _ = probe(conn, row["question"], row.get("as_of"), k)
            want = {(a, u) for a, u in row["expected"]}
            now_rank = next((h["rank"] for h in hits if (h["act"], h["stem"]) in want), None)
            was_rank, cls = b.get("gold_rank"), b.get("class") or "?"
            slot = by_class.setdefault(cls, {"n": 0, "lost": 0, "gained": 0})
            slot["n"] += 1
            if was_rank and not now_rank:
                lost.append((qid, cls, was_rank))
                slot["lost"] += 1
            elif now_rank and not was_rank:
                gained.append((qid, cls, now_rank))
                slot["gained"] += 1
            elif was_rank and now_rank and was_rank != now_rank:
                moved.append((qid, cls, was_rank, now_rank))
    was = header.get("corpus") or {}
    print(f"baseline {base_path.name} (n={header.get('n')}, k={header.get('k')}) vs live")
    print(f"  corpus: {was.get('chunks')} chunks / {was.get('acts')} acts  →  "
          f"{now_shape['chunks']} / {now_shape['acts']}")
    for cls, s in sorted(by_class.items()):
        print(f"  {cls:12s} n={s['n']:3d}  lost={s['lost']}  gained={s['gained']}")
    if moved:
        print("  rank moves (not a regression by itself): " +
              ", ".join(f"{q}:{a}→{b}" for q, _, a, b in moved[:12]))
    if gained:
        print("  GAINED gold: " + ", ".join(f"{q}(@{r})" for q, _, r in gained))
    if lost:
        print("  ⛔ LOST gold: " + ", ".join(f"{q}(was @{r})" for q, _, r in lost))
        print("REGRESSION [RED] — a question that used to retrieve its gold norm no longer does.")
        return 1
    print("no gold lost — [GREEN]")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--out", type=Path, help="capture a new baseline to this path")
    ap.add_argument("--compare", type=Path, help="compare live retrieval against this baseline")
    ap.add_argument("-k", type=int, default=TOP_K)
    a = ap.parse_args()
    if bool(a.out) == bool(a.compare):
        raise SystemExit("choose exactly one: --out (capture) or --compare (check)")
    if a.out:
        capture(a.gold, a.out, a.k)
        return 0
    return compare(a.compare, a.gold, a.k)


if __name__ == "__main__":
    raise SystemExit(main())
