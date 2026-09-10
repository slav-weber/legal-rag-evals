"""Eval runner v0: question → LLM answer (no RAG yet) + traces.

For each question it asks the model (default DeepSeek v4-flash via STRICT
function-calling — public FAQ questions only, which the data policy allows) for a
structured answer {answer, citations[], abstain}, computes a stub metric (does any
citation or the answer mention an article number?), and writes:

  eval/runs/<date>.jsonl         — one RunResult per question
  eval/runs/traces_<date>.jsonl  — one trace per LLM call, from call #1
                                   {t, call, sha1(sysprompt), user, result, request_id}
                                   — a regression corpus collected for free

Backends: --backend deepseek (default) | local (LM Studio fallback) | stub (mocked,
no API — exercises the runner offline). NO gold scoring happens here: the gold
reference answers are written separately, because an eval must not grade itself.

Warning: in production these traces would hold real USER questions and would need a
retention / PII policy first. The traces here hold only PUBLIC FAQ questions — safe.

Run:  uv run python -m eval.runner --limit 5
      uv run python -m eval.runner --backend stub --limit 5
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from eval.schema import EvalQuestion, RunResult  # noqa: E402
from ml import llm_client  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
RUNS = Path(__file__).resolve().parent / "runs"

SYSTEM = (
    "Ти — довідковий помічник з українського права (не адвокат). Відповідай стисло "
    "українською. Якщо знаєш норму — вкажи статтю в citations (напр. «ст. 210-1 "
    "КУпАП»). Якщо не впевнений — став abstain=true і коротко поясни в answer. Не "
    "вигадуй номери статей."
)
# Left boundary so the "ст" inside words like «текст» / «місто» cannot false-match;
# hyphenated article numbers (ст. 210-1) are allowed.
ARTICLE_RE = re.compile(
    r"(?<![А-ЯІЇЄҐа-яіїєґA-Za-z])(?:ст\.?|статт[іяею])\s*\d+(?:-\d+)?", re.IGNORECASE)

# Honest exit: green ONLY if the run actually produced results and the failure rate
# stayed under this bar. Empty input and all-errored runs are failures, not passes;
# a backend SKIP gets its own exit code (2) rather than a green one.
MAX_ERROR_RATE = 0.5
EXIT_SKIP = 2

ANSWER_TOOL = {
    "name": "answer_legal_question",
    "description": "Дай структуровану відповідь на юридичне питання.",
    "parameters": {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "стисла відповідь українською"},
            "citations": {"type": "array", "items": {"type": "string"},
                          "description": "статті/акти, напр. [\"ст. 210-1 КУпАП\"]"},
            "abstain": {"type": "boolean", "description": "true, якщо не впевнений"},
        },
        "required": ["answer", "citations", "abstain"],
    },
}


def _has_article(answer: str, citations: list[str]) -> bool:
    return bool(ARTICLE_RE.search(answer) or any(ARTICLE_RE.search(c) for c in citations))


def _stub(question: str):
    """Mocked model output — lets the runner run with no API."""
    return {"args": {"answer": f"[stub] {question[:40]}…", "citations": ["ст. 0 stub"],
                     "abstain": True}, "pt": 0, "ct": 0, "cache": 0, "rid": "stub",
            "model": "stub"}


def _deepseek(msgs):
    # Generous per-answer budget: a small cap silently truncates the tool-args
    # JSON with finish=length. 1500 comfortably fits a FAQ answer.
    r = llm_client.call_tool_deepseek(msgs, ANSWER_TOOL, max_tokens=1500)
    return {"args": r.args, "pt": r.prompt_tokens, "ct": r.completion_tokens,
            "cache": r.cache_hit_tokens, "rid": r.request_id, "model": r.model}


def _local(msgs):
    """LM Studio fallback (no strict tools) — asks for JSON, parses leniently."""
    r = llm_client.chat(msgs + [{"role": "user", "content":
        "Відповідь ПОВЕРНИ як JSON: {\"answer\":..,\"citations\":[..],\"abstain\":..}"}],
        temperature=0.0, max_tokens=600)
    try:
        args = json.loads(re.search(r"\{.*\}", r.text, re.DOTALL).group(0))
    except Exception:  # noqa: BLE001
        args = {"answer": r.text.strip(), "citations": [], "abstain": False}
    return {"args": args, "pt": r.prompt_tokens, "ct": r.completion_tokens,
            "cache": 0, "rid": "", "model": r.model}


def main() -> int:
    ap = argparse.ArgumentParser(description="Eval runner v0: question → LLM answer + traces")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--backend", choices=["deepseek", "local", "stub"], default="deepseek")
    ap.add_argument("--questions", default=str(DATA / "questions_v0.jsonl"))
    args = ap.parse_args()
    RUNS.mkdir(parents=True, exist_ok=True)

    # Local backend degrades to a clear SKIP when no local chat LLM is served
    # (e.g. MamayLM removed from disk — LM Studio may still serve only embeddings).
    # The path stays verified; this just avoids a cryptic connection error.
    if args.backend == "local":
        try:
            served = llm_client.list_models()
        except Exception:  # noqa: BLE001
            served = None
        if not served or llm_client.DEFAULT_MODEL not in served:
            print(f"SKIP: --backend local — no local chat LLM served "
                  f"(need '{llm_client.DEFAULT_MODEL}'; LM Studio served: {served}). "
                  f"Load a chat model in LM Studio to run the local check. "
                  f"Primary backend is DeepSeek (--backend deepseek).")
            return EXIT_SKIP  # distinct from pass(0)/fail(1) — a real SKIP status

    with Path(args.questions).open(encoding="utf-8") as fh:
        rows = [EvalQuestion(**json.loads(line)) for line in fh]
    rows = rows[:args.limit]
    now = datetime.datetime.now().astimezone()
    # UNIQUE run id down to the second: the earlier %Y-%m-%d stamp CLOBBERED same-day runs of the
    # same backend — a re-run silently overwrote the prior JSONL and broke the replay history.
    stamp = now.strftime("%Y-%m-%d_%H%M%S")
    sys_sha = hashlib.sha1(SYSTEM.encode("utf-8")).hexdigest()
    backends = {"deepseek": _deepseek, "local": _local,
                "stub": lambda m: _stub(m[-1]["content"])}
    call = backends[args.backend]

    # Key by backend too, so a stub/local test never clobbers the DeepSeek run.
    run_path = RUNS / f"{stamp}_{args.backend}.jsonl"
    trace_path = RUNS / f"traces_{stamp}_{args.backend}.jsonl"
    results, traces, n_ref, n_abstain, errors = [], [], 0, 0, 0
    print(f"backend={args.backend}, questions={len(rows)}, model target="
          f"{llm_client.DEEPSEEK_MODEL if args.backend=='deepseek' else args.backend}")

    for i, q in enumerate(rows, 1):
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": q.question}]
        try:
            out = call(msgs)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  ! {q.id}: {exc}")
            traces.append({"t": now.isoformat(), "call": i, "sha1_sys": sys_sha,
                           "user": q.question, "error": str(exc), "request_id": ""})
            continue
        a = out["args"]
        has_ref = _has_article(a.get("answer", ""), a.get("citations", []))
        n_ref += has_ref
        n_abstain += bool(a.get("abstain"))
        results.append(RunResult(
            question_id=q.id, question=q.question, model=out["model"],
            answer=a.get("answer", ""), citations=a.get("citations", []),
            abstain=bool(a.get("abstain")), has_article_ref=has_ref,
            prompt_tokens=out["pt"], completion_tokens=out["ct"],
            cache_hit_tokens=out["cache"], backend=args.backend, run_at=now.isoformat()))
        traces.append({"t": now.isoformat(), "call": i, "sha1_sys": sys_sha,
                       "user": q.question, "result": a, "request_id": out["rid"],
                       "tokens": {"p": out["pt"], "c": out["ct"], "cache": out["cache"]}})
        print(f"  {q.id}: abstain={a.get('abstain')} article_ref={has_ref} "
              f"cit={a.get('citations')}")

    with run_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(r.model_dump_json() + "\n")
    with trace_path.open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    attempted = len(rows)
    error_rate = (errors / attempted) if attempted else 1.0
    passed = attempted > 0 and bool(results) and error_rate <= MAX_ERROR_RATE
    print(f"\nDONE [{'ok' if passed else 'FAIL'}]: {len(results)} answered, "
          f"errors={errors}/{attempted} (error_rate={error_rate:.0%}, "
          f"threshold={MAX_ERROR_RATE:.0%}). stub-metric: article_ref "
          f"{n_ref}/{len(results)}, abstain {n_abstain}/{len(results)}.")
    print(f"  → {run_path.name} + {trace_path.name} in eval/runs/")
    if not passed:
        why = ("no questions loaded (empty input)" if attempted == 0
               else "no successful results" if not results
               else f"error_rate {error_rate:.0%} exceeds {MAX_ERROR_RATE:.0%}")
        print(f"FAIL: {why} — refusing a green exit.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
