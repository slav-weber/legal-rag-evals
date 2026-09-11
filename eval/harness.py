"""Eval harness core: gold loader + mechanical fields + taxonomy + golden corpus + stubs.

Evaluates the full generation pipeline (`generate`) against the reference questions. The
reference set is written by the project's lead agent, never by the model under evaluation — an
eval must not grade itself. This module is the SCORING core:
  - loads the reference questions through the ONE fail-loud gold validator
    (retrieval_eval._load_gold — reused, never re-implemented); it carries gold_citations
    (validated) + gold_key_points + class;
  - `mechanical_fields`: the STABLE fields the gate diffs (cited act / article stem, abstain) —
    NOT prose;
  - `classify`: taxonomy correct / null / wrong_pick-candidate / hallucination (structurally 0,
    an invariant probe) + a precision_drift SIGNAL (the norm is right, the wording drifts —
    lawyer-review territory);
  - golden mechanism (eval/golden/*.jsonl — a curated regression corpus, committed): a
    MECHANICAL case is hard (one mismatch = RED, never auto-rebased); a precision_drift case is a
    measured SIGNAL (prose flips even at temperature 0, so it is not hard-gated in v0);
  - offline backends (mocked generate — the harness runs with no API, no LM and no database).

Storage is files: working runs → $DATA_DIR/eval/t13 (gitignored), golden corpus → eval/golden
(committed). No database is involved in either.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from eval.retrieval_eval import GoldFormatError, _known_acts, _load_gold  # noqa: E402 — reuse

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
ETALONS = Path(__file__).resolve().parent / "data" / "questions_v0.jsonl"

# Set-level replay noise threshold: the two-pass replay is RED if a run's mechanical SET-flip-rate
# exceeds this. Value = the 29x2 LIVE re-measurement of 2026-07-18 (set-flip-rate 0.310; gold-flips
# 0 — the gold citation is stable, the EXTRA cited set is what is noisy) x ~1.45 margin. Set ONLY
# AFTER measuring: a threshold picked before the measurement is a guess. The measurement is a
# persisted artifact: $DATA_DIR/eval/t13/noise_2026-07-18T170800_live.jsonl. GOLD-level flips are a
# HARD incident (any > 0), independent of this rate.
NOISE_FLIP_THRESHOLD = 0.45

# The lint channels a run's detail persists per question, so a flagged phrase stays readable in the
# artifact and not only in the run's stdout.
LINT_KEYS = ("diyi_refs_unbacked", "prose_refs_ambiguous_act", "prose_internal_vocab")


def _stem(unit_path: str) -> str:
    return unit_path.split("/", 1)[0]


def mechanical_fields(result: dict) -> dict:
    """The STABLE fields the gate diffs (NOT prose): the set of cited (act, article-stem) — from
    the candidates whose C-id the model actually cited — and abstain. Plus `outside_set`: resolved
    cids not in the candidate set (structural hallucination probe — MUST be 0, the citation gate
    guarantees it)."""
    by_id = {c["id"]: c for c in result.get("candidates", [])}
    resolved_ids = list(result.get("resolved", {}))
    cited = {(by_id[cid]["act"], _stem(by_id[cid]["unit_path"]))
             for cid in resolved_ids if cid in by_id}
    outside_set = [cid for cid in resolved_ids if cid not in by_id]
    return {"cited": cited, "abstain": bool(result.get("abstained")), "outside_set": outside_set}


def classify(result: dict, expected: list[tuple[str, str]]) -> dict:
    """Taxonomy per reference question. `expected` = gold [(act, ст.N)] (by article).
      correct   — the gold citation IS cited;
      null      — the gold citation is MISSED and the answer did not abstain (a real miss);
      wrong_pick_candidates — a cited (act, article) that backs no gold item (a real norm, maybe
                  not the right one → golden review confirms wrong_pick vs valid context);
      hallucination — a resolved id outside the candidate set (structurally 0; >0 = a breach of
                  the citation gate);
      precision_drift_signal — a gold norm IS cited BUT the prose names article numbers outside
                  the resolved set (prose_lint) → formulation drift (lawyer review; confirmed by
                  a golden case, never auto-RED)."""
    mf = mechanical_fields(result)
    if mf["abstain"]:
        # An abstained dovidka delivers NO citations to the reader (render_dovidka shows ONLY the
        # 'not enough grounds' note) — it must NOT be scored as if it had answered (review fix:
        # correct/wrong_pick/drift were derived from `cited` regardless of abstain → inflated
        # recall). Abstain is tracked on its OWN axis; hallucination stays an invariant probe
        # even here.
        return {"correct": [], "null": [], "wrong_pick_candidates": [],
                "hallucination": len(mf["outside_set"]), "precision_drift_signal": False,
                "abstain": True}
    cited, gold = mf["cited"], set(expected)
    correct = sorted(gold & cited)
    null = sorted(gold - cited)
    wrong_pick = sorted(cited - gold)
    lint = result.get("lint") or {}
    drift = bool(correct) and bool(lint.get("prose_refs_unbacked"))
    return {"correct": correct, "null": null, "wrong_pick_candidates": wrong_pick,
            "hallucination": len(mf["outside_set"]), "precision_drift_signal": drift,
            "abstain": False}


def candidate_stems(result: dict) -> set:
    """All (act, article-stem) pairs in the RETRIEVED candidate set — regardless of whether the
    model cited them. The retrieval UNIVERSE a generation eval can draw from (vs
    mechanical_fields.cited, which is only the SUBSET the model actually cited)."""
    return {(c["act"], _stem(c["unit_path"])) for c in (result.get("candidates") or [])
            if c.get("act") and c.get("unit_path")}


def sufficient_at_k(result: dict, expected) -> dict:
    """sufficient@k: is every gold (act, стаття) PRESENT in the retrieved candidates? This
    separates RETRIEVAL sufficiency (could the generator have cited the gold AT ALL?) from
    GENERATION selection. gold not in candidates is a structural RETRIEVAL miss, not a generation
    error — it is the CEILING of the generation eval (a `null` under insufficient retrieval is not
    the generator's fault). Measured regardless of abstain (retrieval ran either way)."""
    gold = {tuple(e) for e in (expected or [])}
    missing = sorted(gold - candidate_stems(result))
    return {"sufficient": not missing, "missing": missing, "gold_n": len(gold)}


def _zero() -> dict:
    return {"n": 0, "gold": 0, "correct": 0, "null": 0, "wrong_pick": 0, "abstain": 0,
            "drift": 0, "hallucination": 0, "insufficient": 0, "diyi_unbacked": 0,
            "ambiguous_act": 0, "vocab_flags": 0}


def _run_safe(run_fn, row):
    """A single failing reference question (e.g. the model returning finish=length, or a network
    error) must NOT crash the whole run — collect it as an error and move on (harness hygiene,
    mirroring the runner's per-row catch)."""
    try:
        return run_fn(row), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def score(rows: list[dict], run_fn) -> dict:
    """Run each reference question through `run_fn(row) -> result`, classify, aggregate overall +
    by class. run_fn is generate (LIVE) or a stub. Returns metrics + per-question detail +
    errors."""
    agg = _zero()
    by_class: dict = defaultdict(_zero)   # FRESH zeros per class (NOT a copy of the mutated agg)
    detail, errors = [], []
    for row in rows:
        result, err = _run_safe(run_fn, row)
        if err:
            errors.append({"id": row.get("id"), "error": err})
            continue
        tax = classify(result, row["expected"])
        suf = sufficient_at_k(result, row["expected"])   # retrieval ceiling, before generation
        lint = result.get("lint") or {}
        gold_n = len(set(row["expected"]))   # DEDUPED denominator — matches classify's set-based
        #                                       numerator (review fix: a duplicate gold line was
        #                                       undercounting recall, correct 1 / gold 2 = 0.5).
        for bucket in (agg, by_class[row.get("class", "all")]):
            bucket["n"] += 1
            bucket["gold"] += gold_n
            bucket["correct"] += len(tax["correct"])
            bucket["null"] += len(tax["null"])
            bucket["wrong_pick"] += len(tax["wrong_pick_candidates"])
            bucket["abstain"] += int(tax["abstain"])
            bucket["drift"] += int(tax["precision_drift_signal"])
            bucket["hallucination"] += tax["hallucination"]
            bucket["insufficient"] += int(not suf["sufficient"])                   # sufficient@k
            bucket["diyi_unbacked"] += len(lint.get("diyi_refs_unbacked") or [])   # action lint
            bucket["ambiguous_act"] += len(lint.get("prose_refs_ambiguous_act") or [])  # act-scoped
            bucket["vocab_flags"] += len(lint.get("prose_internal_vocab") or [])   # vocab lint
        # PERSIST the dovidka prose so a lint-flagged phrase is re-readable from the artifact, not
        # only re-runnable. SAFE: the harness runs ONLY on reference questions (gold —
        # public/synthetic, PII-free), NEVER on user data. Do NOT reuse write_run for runs over
        # user questions.
        dov = result.get("dovidka") or {}
        prose = {"vysnovok": dov.get("vysnovok") or "",
                 "diyi": [s for s in (dov.get("diyi") or []) if isinstance(s, str)],
                 "tezy": [t.get("teza") or "" for t in (dov.get("obgruntuvannya") or [])]}
        # PIN the retrieved set per question: a replay must diff against the SAME candidate set
        # (the earlier runner pinned nothing). candidates + resolved + request_ids make the run
        # replayable.
        pinned = {"candidates": [[c["id"], c["act"], c["unit_path"]]
                                 for c in result.get("candidates", [])],
                  "resolved": list(result.get("resolved", {})),
                  "request_ids": [a.get("request_id") for a in result.get("attempts", [])]}
        detail.append({"id": row.get("id"), "class": row.get("class"), "taxonomy": tax,
                       "sufficient": suf, "dovidka": prose, "pinned": pinned,
                       "lint": {k: lint.get(k) or [] for k in LINT_KEYS}})
    return {"overall": agg, "by_class": {k: v for k, v in by_class.items()}, "detail": detail,
            "errors": errors}


# ── golden mechanism (eval/golden/*.jsonl; curated regression corpus) ────────────────────────────
class GoldenFormatError(ValueError):
    """A malformed / toothless golden case. FAIL-LOUD: a golden that cannot fail is not a golden,
    and bug_ref is mandatory (a golden case is never auto-rebased)."""


def load_golden(golden_dir: Path = GOLDEN_DIR) -> list[dict]:
    """Golden cases: {bug_ref, question, kind: 'mechanical'|'precision_drift', expect}. Committed.
    FAIL-LOUD: bug_ref required, kind valid, and the case must have TEETH — an expect that can
    actually fail (mechanical needs cited/abstain; precision_drift needs must_not_contain)."""
    cases = []
    for f in sorted(golden_dir.glob("*.jsonl")):
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            c = json.loads(line)
            where = f"golden {f.name}:{lineno}"
            if not c.get("bug_ref"):
                raise GoldenFormatError(f"{where} — bug_ref required (never auto-rebased)")
            kind, exp = c.get("kind"), c.get("expect") or {}
            if kind not in ("mechanical", "precision_drift"):
                raise GoldenFormatError(f"{where} — kind must be mechanical|precision_drift, "
                                        f"got {kind!r}")
            has_teeth = (exp.get("cited") or "abstain" in exp) if kind == "mechanical" \
                else bool(exp.get("must_not_contain"))
            if not has_teeth:                                    # vacuous golden can never fail
                raise GoldenFormatError(f"{where} — toothless expect={exp}: a golden that cannot "
                                        f"fail is not a golden")
            cases.append(c)
    return cases


def check_golden(case: dict, result: dict) -> tuple[bool, list[str]]:
    """Check one golden case against a result. MECHANICAL → hard (one mismatch = RED).
    PRECISION_DRIFT → a measured SIGNAL: must_not_contain a drifted phrase in the prose (reported,
    NOT hard-RED in v0 — prose flips even at temperature 0; it is lawyer-review territory).
    Returns (ok, mismatches)."""
    exp = case.get("expect") or {}
    mism: list[str] = []
    if case.get("kind") == "mechanical":
        mf = mechanical_fields(result)
        if "abstain" in exp and bool(exp["abstain"]) != mf["abstain"]:
            mism.append(f"abstain expected {exp['abstain']} got {mf['abstain']}")
        for act, art in (exp.get("cited") or []):
            if (act, art) not in mf["cited"]:
                mism.append(f"expected cited {act} {art} — not cited")
        return (not mism, mism)
    # precision_drift: signal only (non-gating v0)
    dov = result.get("dovidka", {})
    prose = " ".join([dov.get("vysnovok", "")]
                     + [t.get("teza", "") for t in dov.get("obgruntuvannya", [])])
    hits = [p for p in (exp.get("must_not_contain") or []) if p in prose]
    return (not hits, [f"drift-signal: prose contains «{p}»" for p in hits])


def _stub_run(row: dict) -> dict:
    """Mocked generate result (the harness runs with NO API and NO LM). Echoes the FIRST gold
    citation as a candidate the model 'cited', so the taxonomy path is exercised offline."""
    exp = row.get("expected") or []
    cands = [{"id": f"C{i}", "act": a, "unit_path": art, "citation": f"{a} {art}"}
             for i, (a, art) in enumerate(exp, 1)]
    return {"dovidka": {"vysnovok": "[stub]", "obgruntuvannya": [], "abstain": not exp},
            "resolved": {c["id"]: c["citation"] for c in cands}, "candidates": cands,
            "abstained": not exp, "lint": {"prose_refs_unbacked": [], "leaked_cids": []}}


def _stub_abstain(row: dict) -> dict:
    """A DEGRADED-pipeline stub that ALWAYS abstains / cites nothing — it models a broken pipeline
    so a MECHANICAL golden goes RED. Used by the CLI gate sabotage test: --backend stub-abstain
    must make --mode gate exit 1 (which proves the golden RED leg gates end to end)."""
    return {"dovidka": {"vysnovok": "[stub-abstain]", "obgruntuvannya": [], "abstain": True},
            "resolved": {}, "candidates": [], "abstained": True,
            "lint": {"prose_refs_unbacked": [], "leaked_cids": []}}


def _stub_hallucinate(row: dict) -> dict:
    """A BROKEN-GATE stub: it resolves one citation id that is NOT in its candidate set, the breach
    the citation gate makes structurally impossible in the live pipeline. It exists so a CLI test
    can prove that a hallucination alone turns --mode gate RED; the golden corpus stays green,
    which isolates that branch of the RED condition."""
    base = _stub_run(row)
    return {**base, "resolved": {**base["resolved"], "Cx": "0000-ghost ст.999"}}


_FLIP_STATE = {"n": 0}


def _stub_flip(row: dict) -> dict:
    """A stub whose mechanical SET flips between consecutive passes: every 2nd call adds an extra
    'garnish' citation while the GOLD stays cited (→ gold_flip 0, set_flip 1). It drives the
    noise-exit pin: `--mode noise --backend stub-flip --passes 2` gives a set-flip-rate of 1.0 >
    NOISE_FLIP_THRESHOLD → exit 1, isolating the SET-level (rate) exit branch — GOLD-flips 0 in the
    output proves the gate fired on the rate branch, not on a gold flip (which is the other one).

    NOISE MODE ONLY: the flip is driven by a module-global call counter that alternates on every
    OTHER call — correct only because measure_noise calls run_fn in consecutive per-row PASS pairs
    (call 0/1 = that row's pass 1/pass 2). In --mode score run_fn is called ONCE per row, so this
    would alternate per ROW, which is meaningless. main() GUARDS against that (stub-flip ⇒
    --mode noise)."""
    base = _stub_run(row)
    i = _FLIP_STATE["n"]
    _FLIP_STATE["n"] = i + 1
    if i % 2 == 1:                          # pass 2 of a 2-pass pair: +garnish citation → set flips
        extra = {"id": "Cx", "act": "0000-noise", "unit_path": "ст.999",
                 "citation": "0000-noise ст.999"}
        return {**base, "candidates": base["candidates"] + [extra],
                "resolved": {**base["resolved"], "Cx": extra["citation"]}}
    return base


def _mech_key(result: dict) -> tuple:
    mf = mechanical_fields(result)
    return (frozenset(mf["cited"]), mf["abstain"])


def measure_noise(rows: list[dict], run_fn, passes: int = 2) -> dict:
    """N-pass noise floor — MEASURE the temperature-0 noise FIRST, never guess it; the model is NOT
    deterministic at temperature 0 even on mechanical fields (~2-3% confirmed live). TWO-LEVEL
    comparator:
      - gold_flip (HARD incident): the GOLD article's citation presence differs across passes;
      - set_flip (thresholded): the full mechanical key (cited set + abstain) differs → run
        flip-rate.
    Captures per-pass mechanical detail + request_ids so the measurement is PERSISTABLE via
    write_noise (an uncommitted check is not a check)."""
    detail, set_flips, gold_flips, errs_total = [], 0, 0, 0
    for row in rows:
        gold = set(row.get("expected") or [])
        keys, gold_hits, passes_data, errs = [], [], [], 0
        for _ in range(passes):
            result, err = _run_safe(run_fn, row)
            if err:
                errs += 1
                passes_data.append({"error": err})
                continue
            mf = mechanical_fields(result)
            keys.append((frozenset(mf["cited"]), mf["abstain"]))
            gold_hits.append(bool(gold & mf["cited"]))
            rids = [x.get("request_id") for x in result.get("attempts", [])]
            passes_data.append({"cited": sorted(f"{a} {p}" for a, p in mf["cited"]),
                                "abstain": mf["abstain"], "request_ids": rids})
        set_flip, gold_flip = len(set(keys)) > 1, len(set(gold_hits)) > 1
        set_flips += set_flip
        gold_flips += gold_flip
        errs_total += errs
        detail.append({"id": row.get("id"), "set_flip": set_flip, "gold_flip": gold_flip,
                       "errors": errs, "passes": passes_data})
    n = len(rows) or 1
    return {"passes": passes, "n": len(rows), "set_flip_rate": set_flips / n,
            "set_flips": set_flips, "gold_flips": gold_flips, "errors": errs_total,
            "detail": detail}


def _golden_expected(case: dict) -> list[tuple[str, str]]:
    """The mechanical golden's expected citations as (act, art) — passed to run_fn so an ORACLE
    stub (which echoes `expected`) SATISFIES a satisfiable mechanical case (green), while a
    degraded run (stub-abstain, or a regressed LIVE pipeline that ignores `expected`) FAILS it
    (RED)."""
    return [tuple(c) for c in ((case.get("expect") or {}).get("cited") or [])]


def run_golden(cases: list[dict], run_fn) -> dict:
    """Run each golden case's question through run_fn and check_golden. A MECHANICAL mismatch →
    RED (it gates the run). A PRECISION_DRIFT hit → a signal (reported, non-gating in v0 — prose
    flips)."""
    mechanical_red, drift_signals, detail = [], [], []
    for c in cases:
        result = run_fn({"question": c["question"], "expected": _golden_expected(c), "as_of": None})
        ok, mism = check_golden(c, result)
        detail.append({"bug_ref": c["bug_ref"], "kind": c.get("kind"), "ok": ok,
                       "mismatches": mism})
        if not ok:
            bucket = mechanical_red if c.get("kind") == "mechanical" else drift_signals
            bucket.append(c["bug_ref"])
    return {"mechanical_red": mechanical_red, "drift_signals": drift_signals, "detail": detail}


def _run_dir() -> Path:
    base = os.getenv("DATA_DIR") or str(Path(__file__).resolve().parents[1] / "data")
    d = Path(base) / "eval" / "t13"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_run(res: dict, run_id: str, golden: dict | None = None) -> Path:
    """Persist a run — overall / by-class metrics + the PINNED candidate set & taxonomy per
    reference question — to $DATA_DIR/eval/t13/<run_id>.jsonl (data, not git; a UNIQUE run_id means
    no clobbering, which the earlier runner allowed). This enables a two-pass replay on the SAME
    candidate set. The header also persists the GOLDEN verdict (mechanical_red / drift_signals ids)
    so the gate's golden result is re-readable from the artifact, not only from stdout."""
    header = {"run_id": run_id, "overall": res["overall"], "by_class": res["by_class"]}
    if golden is not None:
        header["golden"] = {"mechanical_red": golden.get("mechanical_red", []),
                            "drift_signals": golden.get("drift_signals", [])}
    path = _run_dir() / f"{run_id}.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(header, ensure_ascii=False) + "\n")
        for d in res["detail"]:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    return path


def write_noise(noise: dict, run_id: str) -> Path:
    """Persist a noise measurement to $DATA_DIR/eval/t13/noise_<run_id>.jsonl: the measurement MUST
    be a stored artifact — per-pass mechanical keys + request_ids + cited sets, not just a number
    quoted in prose."""
    path = _run_dir() / f"noise_{run_id}.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        head = {k: v for k, v in noise.items() if k != "detail"}
        fh.write(json.dumps(head, ensure_ascii=False) + "\n")
        for d in noise["detail"]:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    return path


def _acts_from_gold(path: Path) -> set[str]:
    """The act numbers the gold file itself names — the OFFLINE substitute for the database's
    `SELECT DISTINCT act_nreg FROM chunks`. An offline run has no corpus to check against, so the
    act-exists leg of the validator is satisfied from the file; every OTHER fail-loud check in
    `_load_gold` (two-token citation form, ст.N shape, gold_key_points / theme types) still runs
    unchanged. Pass --known-acts to validate against an explicit list instead."""
    acts: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("expected_act"):                      # smoke format
            acts.add(str(row["expected_act"]))
        for citation in row.get("gold_citations", []):   # 'act_nreg ст.N' — the act is token 1
            parts = str(citation).split()
            if parts:
                acts.add(parts[0])
    return acts


def main() -> int:
    ap = argparse.ArgumentParser(description="Eval harness + gate over the reference questions")
    ap.add_argument("--etalons", default=str(ETALONS),
                    help="reference-question (gold) file to score against")
    ap.add_argument("--backend",
                    choices=["stub", "stub-abstain", "stub-flip", "stub-hallucinate", "live"],
                    default="stub")
    ap.add_argument("--mode", choices=["score", "gate", "noise"], default="score")
    ap.add_argument("--no-llm", action="store_true",
                    help="deterministic tier only: gold format + golden shape/teeth, NO API/LM")
    ap.add_argument("--known-acts", default="",
                    help="comma-separated act numbers to validate gold citations against; "
                         "offline the default is the acts named by the gold file itself")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.backend == "stub-flip" and args.mode != "noise":       # guard
        print("!! --backend stub-flip is a NOISE-mode fixture ONLY: its module-global counter "
              "alternates per PASS (correct for measure_noise's consecutive 2-pass pairs); in "
              "--mode score run_fn is called once per row → it would alternate per-ROW, "
              "meaningless. Use --mode noise.")
        return 2

    # OFFLINE PATHS TOUCH NO DATABASE. Only the live-LLM branch needs a connection, because only
    # `generate(conn, ...)` reads the corpus; the stub backends and --no-llm resolve the known acts
    # from the gold file (or --known-acts) and never even import pipelines.db.
    needs_db = args.backend == "live" and not args.no_llm
    if needs_db:
        from pipelines.db import connect
        db_ctx = connect()
    else:
        db_ctx = contextlib.nullcontext()
    with db_ctx as conn:
        # DETERMINISTIC checks (run in EVERY tier incl. --no-llm): the gold file validates through
        # the reused fail-loud validator, and the golden corpus loads (shape + TEETH).
        try:
            if args.known_acts:
                known = {a.strip() for a in args.known_acts.split(",") if a.strip()}
            elif conn is not None:
                known = _known_acts(conn)
            else:
                known = _acts_from_gold(Path(args.etalons))
            rows = _load_gold(Path(args.etalons), known)
            golden = load_golden()
        except (GoldFormatError, GoldenFormatError) as exc:
            print(f"!! FORMAT ERROR — {exc}")
            return 2

        if args.no_llm:                                            # deterministic tier only
            print(f"gate --no-llm [GREEN]: reference questions OK ({len(rows)} rows), golden OK "
                  f"({len(golden)} cases, teeth+bug_ref validated). No LLM called.")
            return 0

        scorable = [r for r in rows if r["expected"]]
        if not scorable:
            print(f"!! no scorable reference questions in {args.etalons} ({len(rows)} rows, gold "
                  f"empty — that gold is written in a separate review pass). Check the mechanics "
                  f"with --backend stub --etalons eval/data/retrieval_gold_v0.jsonl.")
            return 1
        if args.limit:
            scorable = scorable[:args.limit]

        if args.backend == "stub":
            run_fn = _stub_run
        elif args.backend == "stub-abstain":
            run_fn = _stub_abstain
        elif args.backend == "stub-hallucinate":
            run_fn = _stub_hallucinate                             # gate-breach pin: → RED
        elif args.backend == "stub-flip":
            run_fn = _stub_flip                                    # noise-exit pin: set flips → RED
        else:
            from pipelines.rag.generate import generate

            def run_fn(row):                          # the ONLY branch that consumes the database
                return generate(conn, row["question"], as_of=row.get("as_of"))

        if args.mode == "noise":                     # MEASURE the temperature-0 noise FIRST
            noise = measure_noise(scorable, run_fn, args.passes)
            run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S") + f"_{args.backend}"
            npath = write_noise(noise, run_id)                    # PERSIST the measurement
            red = noise["gold_flips"] > 0 or noise["set_flip_rate"] > NOISE_FLIP_THRESHOLD
            print(f"noise [{args.backend}, {noise['passes']} passes, n={noise['n']}]: "
                  f"set-flip-rate {noise['set_flip_rate']:.3f} (thr {NOISE_FLIP_THRESHOLD}), "
                  f"GOLD-flips {noise['gold_flips']} (hard incidents), "
                  f"{noise['errors']} pass-errors "
                  f"→ {npath.name}. REPLAY [{'RED' if red else 'GREEN'}].")
            return 1 if red else 0        # RED: a gold flip (hard) OR a rate over the threshold

        res = score(scorable, run_fn)
        # The golden corpus gates ALL backends: an ORACLE stub satisfies a satisfiable mechanical
        # golden, while stub-abstain and a regressed live pipeline fail it.
        gr = run_golden(golden, run_fn)
        run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S") + f"_{args.backend}"
        run_path = write_run(res, run_id, gr)   # pinned run + golden verdict in the header
        a = res["overall"]
        print(f"harness [{args.backend}]: {a['n']} reference questions, gold {a['gold']} · run "
              f"→ {run_path.name}")
        print(f"  correct {a['correct']}/{a['gold']} · null {a['null']} "
              f"· wrong_pick-cand {a['wrong_pick']} · abstain {a['abstain']} "
              f"· drift-signal {a['drift']} · hallucination {a['hallucination']}")
        print(f"  sufficient@k {a['n'] - a['insufficient']}/{a['n']} "
              f"(insufficient {a['insufficient']}) · diyi-unbacked {a['diyi_unbacked']} "
              f"· act-ambiguous {a['ambiguous_act']}"
              f"\n  internal-vocab-flags {a['vocab_flags']}")
        for cls, c in sorted(res["by_class"].items()):
            print(f"    {cls:12s} correct {c['correct']}/{c['gold']} null {c['null']} "
                  f"wp {c['wrong_pick']} drift {c['drift']}")
        if res.get("errors"):
            print(f"  errors: {len(res['errors'])} reference questions failed "
                  f"({[e['id'] for e in res['errors']]})")
        print(f"  golden: {len(golden)} loaded · mechanical-RED {gr['mechanical_red']} · "
              f"drift-signals {gr['drift_signals']}")

        # GATE: RED on a hard invariant breach (hallucination — a resolved id outside the candidate
        # set) OR a MECHANICAL golden mismatch. Recall/precision thresholds (>=90% / 100%) are
        # MEASURED and reported, not hard-gated here: they are not expected to pass immediately,
        # and the kill criterion is a product decision, not a harness one. Drift signals are
        # reported, non-gating (prose flips). The golden corpus GATES the run.
        red = bool(a["hallucination"]) or bool(gr["mechanical_red"])
        if args.mode == "gate":
            print(f"GATE [{'RED' if red else 'GREEN'}]: hallucination={a['hallucination']} "
                  f"golden-mechanical-RED={gr['mechanical_red']}")
            return 1 if red else 0
        return 1 if a["hallucination"] else 0            # score mode: hallucination is fatal
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
