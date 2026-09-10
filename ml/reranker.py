"""Cross-encoder reranker (bge-reranker-v2-m3) over the RRF top-N candidates.

The rerank score is EPHEMERAL — no cache, no schema. This is the FINAL layer of the hybrid
retriever: RRF fusion is RECALL (get the target into the top-N); the reranker is PRECISION (reorder
the finalists with a cross-encoder that reads query+doc TOGETHER, unlike the bi-encoder embedder).
RRF order within the top-N need not be perfect — that is exactly what the reranker fixes (RRF-rank
bias is moot once the reranker runs).

Serving: FlagEmbedding IN-PROCESS on the RTX 4080 GPU (NOT LM Studio — the reranker is a separate
OSS model, not served over :1234). fp16 → ~1.1 GB VRAM (embedder ~3.7 GB + reranker « 16 GB —
both fit). Verified live: rr.model on cuda:0, torch.float16.

Model pin (mirror of the embedder's reference-vector, ml/embed_index.check_pin): the model name
lives in .env (RERANK_MODEL); a committed reference (ml/reranker_reference.json) records canonical
(query, doc) → score pairs + the weights sha256 + the HF revision. Every load re-scores the pairs;
a name mismatch or score drift beyond tolerance is a model SWAP → red (SystemExit) — we refuse to
rerank against an unpinned model, exactly as the embedder refuses to embed. Verified live via the
committed reference + the --check-pin note.

Degradation (honest-R-10 — the project's fail-honestly rule: a missing dependency is reported
loudly, never silently substituted): the reranker is a QUALITY GATE. If it cannot be LOADED (no
GPU, OOM, model absent) the caller gets RerankerUnavailable and must SURFACE it — the ladder falls
back to RRF order (reranker→dense→keyword) but NEVER passes RRF order off as if it were reranked.
This is a LOUDER contract than the graceful channel-degrade inside hybrid(): a missing quality gate
is flagged honestly, not absorbed. Model DRIFT (a wrong model loaded) is a different failure — that
is red/SystemExit, not a degrade: we do not silently rerank against the wrong model.

FlagEmbedding/torch are imported lazily inside _load(), so importing this module needs neither;
without the optional `rerank` extra every load path raises RerankerUnavailable.

Run:
  uv run python -m ml.reranker --gen-reference  # FIRST live run: write the reference (commit it)
  uv run python -m ml.reranker --check-pin      # load + validate the pin (drift → red); prints the note
  uv run python -m ml.reranker --smoke          # rerank a fixture query over a few docs (shows reorder)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"
USE_FP16 = True
SCORE_TOLERANCE = 0.5   # |live - reference| logit; deterministic in-process (Δ=0 across runs), the
#                         margin absorbs a driver/fp16 shift on another box while a model swap (Δ≈6+)
#                         still trips it. Same spirit as the embedder's cosine ≥ 0.9999 threshold.
REFERENCE_PATH = Path(__file__).resolve().parent / "reranker_reference.json"

# canonical pins — one RELEVANT and one IRRELEVANT (query, doc) pair. A wrong reranker drifts the
# absolute scores AND can break the ordering; both are checked. Ukrainian legal domain so a
# wrong-language / wrong-model swap drifts hard (mirror of the embedder's hero-vocabulary REF_STRING).
REF_PAIRS = [
    {"tag": "relevant",
     "query": "Яка відповідальність за порушення правил дорожнього руху?",
     "doc": "Стаття 288. Порушення правил дорожнього руху, що спричинило "
            "пошкодження транспортних засобів."},
    {"tag": "irrelevant",
     "query": "Яка відповідальність за порушення правил дорожнього руху?",
     "doc": "Стаття 23. Гарантії трудових прав громадян України."},
]

_RR_DOWN_HINT = ("the reranker (bge-reranker-v2-m3) does not load — check GPU/VRAM and that the "
                 "model is downloaded (uv run python -m ml.reranker --check-pin). This is "
                 "honest-R-10, NOT a silent fallback to RRF order.")


class RerankerUnavailable(RuntimeError):
    """The reranker model cannot be loaded/run (no GPU, OOM, model absent, FlagEmbedding missing).
    Honest-R-10: the caller SURFACES this and falls back down the ladder (reranker→dense→keyword);
    it must NOT be swallowed into a silent RRF order passed off as reranked."""


_MODEL = None
_PIN_OK = False


def _model_name() -> str:
    return os.getenv("RERANK_MODEL", DEFAULT_MODEL)


def _load():
    """Load FlagReranker once (fp16, GPU). ANY load failure → RerankerUnavailable (honest-R-10)."""
    global _MODEL
    if _MODEL is None:
        try:
            from FlagEmbedding import FlagReranker
            _MODEL = FlagReranker(_model_name(), use_fp16=USE_FP16)
        except Exception as exc:  # noqa: BLE001 — ImportError / OSError / CUDA OOM → unavailable
            raise RerankerUnavailable(
                f"reranker '{_model_name()}' unavailable ({type(exc).__name__}: {exc}). "
                f"{_RR_DOWN_HINT}"
            ) from exc
    return _MODEL


def _score_pairs(pairs: list[list[str]]) -> list[float]:
    """Raw cross-encoder logits (higher = more relevant) for [[query, doc], ...]. May raise
    RerankerUnavailable via _load."""
    rr = _load()
    raw = rr.compute_score(pairs, normalize=False)
    if isinstance(raw, (int, float)):   # compute_score returns a scalar for a single pair
        raw = [raw]
    return [float(x) for x in raw]


def _snapshot_dir() -> str:
    from huggingface_hub import snapshot_download
    return snapshot_download(_model_name())


def _weights_sha() -> str:
    """sha256 of model.safetensors (provenance for the delivery note). Called only at bootstrap —
    hashing 2.27 GB is ~seconds, not something the runtime pin re-does every load."""
    p = Path(_snapshot_dir()) / "model.safetensors"
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _revision() -> str:
    return Path(_snapshot_dir()).name   # the HF snapshot dir is named by the commit revision


def _tag_index(pairs: list[dict], tag: str) -> int:
    return next(i for i, p in enumerate(pairs) if p["tag"] == tag)


def check_pin() -> str:
    """Re-score the canonical pairs and compare to the committed reference. First run BOOTSTRAPS it
    (writes + records sha/revision — COMMIT it). A model-name mismatch or a score drift beyond
    tolerance → SystemExit (a model swap, refuse to rerank). RerankerUnavailable propagates (that is
    honest-R-10, a load failure, NOT a drift). Returns a human status line."""
    name = _model_name()
    pairs = [[p["query"], p["doc"]] for p in REF_PAIRS]
    live = _score_pairs(pairs)   # RerankerUnavailable propagates here on a load failure
    if not REFERENCE_PATH.exists():
        REFERENCE_PATH.write_text(json.dumps(
            {"model": name, "use_fp16": USE_FP16, "tolerance": SCORE_TOLERANCE,
             "sha256": _weights_sha(), "revision": _revision(),
             "pairs": [{**p, "score": s} for p, s in zip(REF_PAIRS, live)]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        return (f"reference BOOTSTRAPPED → {REFERENCE_PATH.name} (model {name}) — COMMIT it "
                f"(the pin is generated by the first live run)")
    ref = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    if ref["model"] != name:
        raise SystemExit(f"reranker pin drift: reference is '{ref['model']}', .env RERANK_MODEL is "
                         f"'{name}'. Refusing to rerank against an unpinned model (not a fallback).")
    tol = ref.get("tolerance", SCORE_TOLERANCE)
    ref_pairs = ref["pairs"]
    for rp, live_s in zip(ref_pairs, live):
        if abs(live_s - rp["score"]) > tol:
            raise SystemExit(
                f"RERANKER DRIFT: pair '{rp['tag']}' scored {live_s:.4f}, reference {rp['score']:.4f} "
                f"(|Δ| {abs(live_s - rp['score']):.4f} > tol {tol}) — a DIFFERENT model is loaded on "
                f"'{name}'. Refusing to rerank against an unpinned model (not a fallback).")
    ri, ii = _tag_index(ref_pairs, "relevant"), _tag_index(ref_pairs, "irrelevant")
    if live[ri] <= live[ii]:
        raise SystemExit(f"RERANKER DRIFT: relevant pair ({live[ri]:.3f}) no longer outscores "
                         f"irrelevant ({live[ii]:.3f}) — model integrity broken.")
    return (f"pin OK: {len(live)} reference pairs within ±{tol} (relevant {live[ri]:.3f} > "
            f"irrelevant {live[ii]:.3f}), model {name}")


def rerank(query: str, docs: list[str]) -> list[float]:
    """Cross-encoder relevance scores (logits, higher = better) for (query, doc) pairs, in doc order.
    Validates the model pin ONCE per process (drift → SystemExit; bootstraps if the reference is
    missing). Raises RerankerUnavailable if the model cannot be loaded (honest-R-10). Empty → []."""
    global _PIN_OK
    if not docs:
        return []
    if not _PIN_OK:
        check_pin()          # validate once; drift → SystemExit; RerankerUnavailable propagates
        _PIN_OK = True
    return _score_pairs([[query, d] for d in docs])


def _device_note() -> str:
    rr = _load()
    m = getattr(rr, "model", None)
    if m is None:
        return "device unknown (no .model attr)"
    p = next(m.parameters())
    return f"device {p.device} dtype {p.dtype}"


def main() -> int:
    ap = argparse.ArgumentParser(description="bge-reranker-v2-m3 cross-encoder reranker")
    ap.add_argument("--gen-reference", action="store_true",
                    help="write reranker_reference.json (first live run — commit it)")
    ap.add_argument("--check-pin", action="store_true", help="load + validate the pin (drift → red)")
    ap.add_argument("--smoke", action="store_true", help="rerank a fixture query over a few docs")
    args = ap.parse_args()

    try:
        if args.gen_reference:
            if REFERENCE_PATH.exists():
                print(f"{REFERENCE_PATH.name} already exists — delete it to regenerate")
                return 0
            print(check_pin())   # bootstraps + writes
            return 0
        if args.check_pin:
            print(check_pin())
            print(f"  {_device_note()}")
            return 0
        if args.smoke:
            print(check_pin())
            print(f"  {_device_note()}")
            q = "Яка відповідальність за порушення правил дорожнього руху?"
            docs = [
                "Стаття 288. Порушення правил дорожнього руху, що спричинило пошкодження ТЗ.",
                "Стаття 23. Гарантії трудових прав громадян України.",
                "Стаття 210-1. Порушення порядку ведення військового обліку.",
            ]
            scores = rerank(q, docs)
            order = sorted(zip(scores, docs), key=lambda sd: sd[0], reverse=True)
            print(f"\nsmoke query: {q}")
            for s, d in order:
                print(f"  {s:9.4f}  {d[:60]}")
            return 0
    except RerankerUnavailable as exc:
        print(f"\n!! reranker UNAVAILABLE (honest-R-10): {exc}", file=sys.stderr)
        return 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
