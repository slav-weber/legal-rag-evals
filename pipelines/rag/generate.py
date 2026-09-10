"""Generation with the STRUCTURAL citation gate (the CORE of the system).

Design rule "the LLM picks an ID, code arbitrates": the model may cite ONLY candidate IDs (C1..Ck)
from the retrieved set handed to it in the prompt; a deterministic resolver maps each ID → the exact
citation string from the DB; an ID OUTSIDE the set is REJECTED → regenerate (max 2) → honest
abstain. A hallucinated citation is thus STRUCTURALLY IMPOSSIBLE — an invariant, not a prompt
instruction (prompt wording about citation accuracy is UX polish, never the assurance layer).

- Candidate ID = C1..Ck: a closed per-request dictionary — minimal hallucination surface; internal
  structure (hashes / unit_path) never leaks to the LLM. Rendered «C3: {citation} — текст».
- Citations are act-aware: chunks.citation carries NO act_title (the source of the 78 cross-act
  «ст.5» collisions), so the string is composed «{act_title}, {citation}».
- Data red line: generation runs on reference / synthetic questions ONLY — never real client facts
  (`_guard_deepseek` refuses USER_DATA). Open data (laws, ЄДРСР texts, FAQ) flows freely.
- This module carries the gate mechanism, the resolver and retry/abstain, plus kind-aware dedup, the
  context budget, dovidka rendering and the trace files (→ $DATA_DIR/traces/t12).
"""

from __future__ import annotations

import hashlib
import html as _html
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines.rag.retrieval import natkey  # noqa: E402 — natural leaf order

MAX_RETRIES = 2            # ID-outside-set → regenerate up to twice, then honest abstain
GEN_K = 10                 # retrieval top-k for generation (measured recall@10 = 1.000; k=6 was
#                            flaky — ст.23 ч.1 fell outside the candidate set; budget tail-drops)

_CID_RE = re.compile(r"\bC\d+\b")                       # internal candidate IDs (Latin C + digits)
_ARTNUM_RE = re.compile(r"(?:статт\w*|ст)\.?\s*(\d+(?:-\d+)?)", re.IGNORECASE)   # «ст.N» in prose

# INTERNAL VOCABULARY that must never reach user-visible prose. Our retrieval plumbing
# («кандидати», C-ids, prompt/retrieval jargon) says nothing to a citizen — «Надані кандидати (–)
# не містять норм…» was seen on screen. FLAG, not a gate (the same policy as the other prose lints).
# ⚠ known limit: «кандидат» is also a legitimate legal word (кандидат у народні депутати, кандидат на
# посаду судді) → false positives are possible on election/appointment questions. Acceptable because
# this is a REVIEW SIGNAL, not a block; revisit if the flag proves noisy on the reference questions.
_INTERNAL_VOCAB = (
    ("cid", _CID_RE),
    ("кандидат", re.compile(r"кандидат", re.IGNORECASE)),
    ("промпт", re.compile(r"промпт", re.IGNORECASE)),
    ("retrieval", re.compile(r"\bretrieval\b", re.IGNORECASE)),
    ("candidate", re.compile(r"\bcandidates?\b", re.IGNORECASE)),
)
CONTEXT_BUDGET_TOKENS = 10000   # (~8–12k): tail-drop WHOLE candidates, NEVER truncate text.

_SYSTEM = (
    "Ти — юридичний асистент для військовозобов'язаних України. Відповідай УКРАЇНСЬКОЮ. "
    "Використовуй ВИКЛЮЧНО надані кандидати (норми з набору C1..Ck) — не додавай норм із пам'яті. "
    "У полі citations КОЖНОЇ тези посилайся ТІЛЬКИ на ID кандидатів (C1, C2, …) — вільний текст "
    "«ст. X Закону Y» ЗАБОРОНЕНИЙ (рендер цитат робить код за ID). Якщо кандидатів недостатньо для "
    "обґрунтованої відповіді — постав abstain=true і не вигадуй. Структура: короткий висновок простою "
    "мовою, практичні дії, правове обґрунтування (тези з посиланнями на кандидати)."
)

# Two-layer dovidka: висновок простою мовою + дії + правове обґрунтування (теза + citations).
# Citations are per-теза: per-claim citations are cheap — it is only a schema.
CITATION_TOOL = {
    "name": "pravova_dovidka",
    "description": "Сформувати правову довідку українською; цитати — ТІЛЬКИ ID кандидатів (C1..Ck).",
    "parameters": {
        "type": "object",
        "properties": {
            "vysnovok": {"type": "string",
                         "description": "Висновок простою мовою, 2–4 речення."},
            "diyi": {"type": "array", "items": {"type": "string"},
                     "description": "Практичні кроки (що робити), по порядку."},
            "obgruntuvannya": {
                "type": "array",
                "description": "Правове обґрунтування: тези з посиланнями на ID кандидатів.",
                "items": {"type": "object", "properties": {
                    "teza": {"type": "string", "description": "Правова теза."},
                    "citations": {"type": "array", "items": {"type": "string"},
                                  "description": "ID кандидатів (C1..Ck), що підтверджують тезу."},
                }},
            },
            "abstain": {"type": "boolean",
                        "description": "true, якщо кандидатів недостатньо для відповіді з цитатами."},
        },
    },
}


def act_citation(hit: dict) -> str:
    """Act-aware citation «{act_title}, {citation}». chunks.citation lacks the act title
    (source of the 78 cross-act «ст.5» collisions), so «ст.5» of two different acts render distinctly.
    Defensive: no double-prefix if the citation already leads with the title."""
    cit = (hit.get("citation") or "").strip()
    title = (hit.get("act_title") or hit.get("act") or "").strip()
    if not title:
        return cit
    if not cit:
        return title
    return cit if title in cit else f"{title}, {cit}"


def dedup_candidates(hits: list[dict]) -> list[dict]:
    """kind-aware dedup. After the container flip a container ст.N and its leaves ст.N/п.M
    coexist in retrieval — the container's text is the AGGREGATE of the leaves (duplication → wasted
    budget, confused context). Per (act, article-stem) group: if a CONTAINER is present, keep ONLY
    the highest-RANKED member (container subsumes its leaves; but a leaf the reranker put ABOVE the
    container wins — cite the pinpointed part). A group with NO container keeps all its leaves
    (distinct parts) in NATURAL order. Articles ordered by their best retrieval rank."""
    groups: OrderedDict = OrderedDict()
    for i, h in enumerate(hits):
        stem = h["unit_path"].split("/", 1)[0]
        groups.setdefault((h["act"], stem), []).append((i, h))
    ranked_groups: list[tuple[int, list[dict]]] = []
    for (_act, stem), members in groups.items():
        grank = min(i for i, _h in members)
        if any(h["unit_path"] == stem for _i, h in members):       # container present → subsume
            block = [min(members, key=lambda m: m[0])[1]]
        else:                                                      # leaves only → all, natural order
            block = [h for _i, h in sorted(members, key=lambda m: natkey(m[1]["unit_path"]))]
        ranked_groups.append((grank, block))
    ranked_groups.sort(key=lambda g: g[0])
    return [h for _grank, block in ranked_groups for h in block]


def _apply_budget(candidates: list[dict], max_tokens: int) -> list[dict]:
    """Tail-drop WHOLE candidates once cumulative n_tokens would exceed the budget — texts are NEVER
    truncated (a truncated norm is more dangerous than an absent one). Always keeps ≥1."""
    out: list[dict] = []
    used = 0
    for c in candidates:
        nt = c.get("n_tokens") or 0
        if out and used + nt > max_tokens:
            break
        out.append(c)
        used += nt
    return out


def build_candidates(conn, hits: list[dict],
                     max_tokens: int = CONTEXT_BUDGET_TOKENS) -> tuple[list[dict], dict]:
    """Retrieved hits → (C1..Ck candidate-set, dropped-report): kind-aware dedup → fetch
    text/act_title/n_tokens from `chunks` (hits carry only citations) → DROP a candidate whose text
    is empty (hash-miss guard) → context-budget tail-drop → assign C-numbers over the FINAL set (so
    C1..Ck are contiguous). The act-aware citation is composed here. The dropped-report surfaces
    what was cut — a silent drop is our antipattern."""
    hits = dedup_candidates(hits)
    hashes = list({h["content_hash"] for h in hits if h.get("content_hash")})
    meta: dict[str, tuple[str, str, int]] = {}
    if hashes:
        with conn.cursor() as cur:
            cur.execute("SELECT content_hash, text, act_title, n_tokens FROM chunks "
                        "WHERE content_hash = ANY(%s)", (hashes,))
            meta = {ch: (txt, at, nt) for ch, txt, at, nt in cur.fetchall()}
    enriched: list[dict] = []
    dropped_empty: list[str] = []
    for h in hits:
        text, act_title, nt = meta.get(h.get("content_hash"), ("", h.get("act", ""), 0))
        if not (text or "").strip():
            dropped_empty.append(h["unit_path"])                   # hash-miss / empty text → skip
            continue
        enriched.append({"citation": act_citation({**h, "act_title": act_title}), "act": h["act"],
                         "unit_path": h["unit_path"], "content_hash": h.get("content_hash"),
                         "text": text, "n_tokens": nt or 0})
    kept = _apply_budget(enriched, max_tokens)
    dropped = {"empty_text": dropped_empty,
               "budget": [e["unit_path"] for e in enriched[len(kept):]],
               "n_before": len(enriched), "n_kept": len(kept)}
    return [{"id": f"C{i}", **e} for i, e in enumerate(kept, 1)], dropped


def render_candidates(candidates: list[dict]) -> str:
    """The volatile candidate block for the USER message (the byte-stable system prompt stays the
    cache prefix). «C1: {citation} — {text}»."""
    return "\n".join(f"{c['id']}: {c['citation']} — {c['text']}" for c in candidates)


def _cited_ids(dovidka: dict) -> list[str]:
    ids: list[str] = []
    for item in dovidka.get("obgruntuvannya") or []:
        ids.extend(item.get("citations") or [])
    return ids


def resolve_citations(dovidka: dict, candidates: list[dict]) -> tuple[dict, list[str]]:
    """(resolved {id: citation_string}, invalid [ids outside the set]). The GATE: any cited ID not in
    the candidate set is invalid → the caller rejects/regenerates. Deduped, order-preserving."""
    by_id = {c["id"]: c["citation"] for c in candidates}
    resolved: dict[str, str] = {}
    invalid: list[str] = []
    for cid in _cited_ids(dovidka):
        if cid in by_id:
            resolved[cid] = by_id[cid]
        elif cid not in invalid:
            invalid.append(cid)
    return resolved, invalid


def _prose_strings(dovidka: dict) -> list[str]:
    out = [dovidka.get("vysnovok") or ""]
    out += [s for s in (dovidka.get("diyi") or []) if isinstance(s, str)]
    out += [(item.get("teza") or "") for item in (dovidka.get("obgruntuvannya") or [])]
    return out


def _resolved_num_acts(resolved: dict, candidates: list[dict] | None) -> dict:
    """article-number → {act keys} across the RESOLVED citations, using the candidate's canonical `act`
    (nreg) metadata. For the act-scoped lint: a number backed by >1 act is act-ambiguous (the cross-act
    «ст.5» collision class). resolved is {id: citation}; the act lives on the candidate, not the string."""
    by_id = {c["id"]: c for c in (candidates or [])}
    num_acts: dict[str, set] = {}
    for cid in resolved:
        c = by_id.get(cid)
        if not c:
            continue
        act = (c.get("act") or "").strip()
        nums = _ARTNUM_RE.findall(c.get("unit_path") or "") or _ARTNUM_RE.findall(c.get("citation") or "")
        for num in nums:
            num_acts.setdefault(num, set()).add(act)
    return num_acts


def prose_lint(dovidka: dict, resolved: dict, candidates: list[dict] | None = None) -> dict:
    """Prose safety flags (policy BY MEASUREMENT — FLAG, do not reject):
    - prose_refs_unbacked: article numbers named in FREE TEXT (vysnovok/дії/teza) whose number is not
      in ANY resolved citation — potential pseudo-citations the LLM wrote in prose instead of via IDs.
    - leaked_cids: internal candidate IDs (C1..Ck) that leaked into user-visible prose — these MUST be
      stripped from the rendered HTML (a live finding: abstain-prose leaked «C1–C6»).
    - diyi_refs_unbacked (the дії lint): the unbacked-number subset named specifically in the дії
      (ACTION) layer — higher-risk, isolated (users ACT on дії, so an unbacked ref there is worse than
      the same ref in обґрунтування).
    - prose_refs_ambiguous_act (act-scoped): prose article-numbers backed by resolved
      citations of MORE THAN ONE act — the number is 'backed' yet the reference is act-ambiguous (the
      cross-act «ст.5» collision; a bare-number check reports «backed» and hides it — act scope reveals it).
    - prose_internal_vocab: INTERNAL vocabulary leaked into user-visible prose — C-ids,
      «кандидат…», «промпт», «retrieval», «candidate». Our retrieval plumbing must never be shown to a
      citizen («Надані кандидати (–) не містять норм…» was seen live). Reports CLASSES, not hits."""
    prose = " ".join(_prose_strings(dovidka))
    prose_nums = set(_ARTNUM_RE.findall(prose))
    resolved_nums = set(_ARTNUM_RE.findall(" ".join(resolved.values())))
    diyi_nums = set(_ARTNUM_RE.findall(" ".join(s for s in (dovidka.get("diyi") or []) if isinstance(s, str))))
    num_acts = _resolved_num_acts(resolved, candidates)
    return {"prose_refs_unbacked": sorted(prose_nums - resolved_nums),
            "leaked_cids": sorted(set(_CID_RE.findall(prose))),
            "diyi_refs_unbacked": sorted(diyi_nums - resolved_nums),
            "prose_refs_ambiguous_act": sorted(n for n in prose_nums if len(num_acts.get(n, ())) > 1),
            # internal vocabulary anywhere in user-visible prose (висновок + дії + тези)
            "prose_internal_vocab": sorted({name for name, rx in _INTERNAL_VOCAB if rx.search(prose)})}


def _result(dovidka: dict, resolved: dict, candidates: list[dict], abstained: bool,
            attempts: list[dict], route, dropped: dict, reason: str | None = None) -> dict:
    r = {"dovidka": dovidka, "resolved": resolved, "candidates": candidates, "abstained": abstained,
         "attempts": attempts, "route": route, "dropped": dropped,
         "lint": prose_lint(dovidka, resolved, candidates)}
    if reason:
        r["abstain_reason"] = reason
    return r


def _abstain_dovidka(reason_note: str) -> dict:
    return {"vysnovok": reason_note, "diyi": [], "obgruntuvannya": [], "abstain": True}


def generate(conn, question: str, as_of=None, k: int = GEN_K, max_retries: int = MAX_RETRIES) -> dict:
    """Question → правова довідка with GATED citations (+ trace fields). Retrieves top-k (k=10 =
    measured recall@10 = 1.000), hands the C1..Ck candidate set to DeepSeek strict
    function-calling, resolves the cited IDs; an ID outside the set OR a citation-free dovidka →
    regenerate (max_retries) → honest abstain. Result carries dovidka, resolved, candidates, dropped
    (budget/empty surfacing), prose lint flags, and per-attempt trace data (request_id → replayable)."""
    from ml.llm_client import call_tool_deepseek
    from pipelines.rag.retrieval import search

    hits, meta = search(conn, question, as_of=as_of, k=k)
    candidates, dropped = build_candidates(conn, hits)
    route = meta.get("route")
    degraded, reranked = meta.get("degraded", []), meta.get("reranked", False)

    def _final(res: dict) -> dict:
        # Surface the retrieval-layer honest-R-10 degradation into the result:
        # search() flags a fallen channel/reranker in meta['degraded'] / meta['reranked'], but this
        # function otherwise keeps only `route` — so the API meta could not report a fallback and would
        # look healthy. Additive: gate/resolver untouched.
        res["degraded"], res["reranked"] = degraded, reranked
        return res

    if not candidates:
        return _final(_result(_abstain_dovidka("Недостатньо підстав у наданому наборі."), {}, candidates,
                              True, [], route, dropped, "no candidates retrieved"))

    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user",
                 "content": f"Кандидати:\n{render_candidates(candidates)}\n\nПитання: {question}"}]
    ids = ", ".join(f"C{i}" for i in range(1, len(candidates) + 1))
    attempts: list[dict] = []
    for _attempt in range(max_retries + 1):
        # 3000: a rich dovidka (many obgruntuvannya тези + дії) exceeded the old 1500 cap → DeepSeek
        # truncated the tool-args JSON with finish=length (surfaced by the replay-noise run).
        r = call_tool_deepseek(messages, CITATION_TOOL, temperature=0.0, max_tokens=3000)
        dovidka = r.args
        resolved, invalid = resolve_citations(dovidka, candidates)
        attempts.append({"request_id": r.request_id, "prompt_tokens": r.prompt_tokens,
                         "completion_tokens": r.completion_tokens, "cache_hit_tokens": r.cache_hit_tokens,
                         "invalid_ids": invalid, "n_resolved": len(resolved),
                         "abstain": bool(dovidka.get("abstain"))})
        if dovidka.get("abstain"):
            return _final(_result(dovidka, resolved, candidates, True, attempts, route, dropped,
                                  "model abstained"))
        problem = None
        if invalid:                                                # ID outside the set → reject
            problem = (f"Цитати {invalid} — НЕ з набору кандидатів і відхилені. Використай ВИКЛЮЧНО "
                       f"наявні ID: {ids}. Якщо підстав немає — abstain=true.")
        elif not resolved:                                         # MANDATORY: no citation → reject
            problem = (f"Жодна теза не має посилання. Справка без посилань недійсна — кожна теза "
                       f"обґрунтування МУСИТЬ мати citations з ID {ids}. Додай або abstain=true.")
        if problem is None:
            return _final(_result(dovidka, resolved, candidates, False, attempts, route, dropped))
        # reconstruct the assistant tool-call turn + tool response before regenerating: a bare
        # [system,user,user] worked live but is API-fragile — the protocol wants the assistant
        # tool_call + a tool message answering its id before the next forced call.
        messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": r.tool_call_id, "type": "function",
             "function": {"name": CITATION_TOOL["name"], "arguments": r.raw_arguments}}]})
        messages.append({"role": "tool", "tool_call_id": r.tool_call_id, "content": problem})
    return _final(_result(_abstain_dovidka("Недостатньо підстав у наданому наборі для відповіді з "
                          "посиланнями."), {}, candidates, True, attempts, route, dropped,
                          "no valid citations after retries"))


def _clean(text: str) -> str:
    """Strip leaked internal candidate IDs (C1..Ck) from user-visible prose (a live finding:
    abstain-prose leaked «C1–C6» into the HTML) and collapse the resulting whitespace."""
    return re.sub(r"\s{2,}", " ", _CID_RE.sub("", text or "")).strip(" ,;")


# ── DETERMINISTIC abstain copy ───────────────────────────────────────────────────────────────────
# The model still DECIDES to abstain, but its PROSE never reaches the screen. A live finding on the
# first question outside the reference set: «Надані кандидати (–) не містять норм…» — two defects in
# one line: «кандидати» is our retrieval plumbing (meaningless to a citizen) and the C-ID filter had
# cut «C1/C9», leaving a mutilated bracket. A structural fix, NOT prompt polishing. The copy below
# is approved wording — VERBATIM, not to be edited. The model's own reason goes to the TRACE
# (write_trace), never to the UI.
ABSTAIN_VYSNOVOK = ("На це запитання ми не можемо дати обґрунтовану відповідь: у чинних нормах, "
                    "доступних системі, ми не знайшли підстав, на які можна прямо послатися.")
ABSTAIN_DIYI = (
    "Спробуйте сформулювати запитання конкретніше — назвіть орган, рішення та дату.",
    "Можливо, ваше питання регулюють норми, яких поки немає в нашій базі, — це не означає, "
    "що відповіді не існує.",
    "У такій ситуації варто звернутися до адвоката: довідка не замінює правову допомогу.",
)


def render_dovidka(result: dict, question: str = "") -> str:
    """Two-layer dovidka as a self-contained HTML fragment: висновок простою мовою + дії + правове
    обґрунтування, each теза carrying citation CHIPS resolved to the act-aware string. An abstained
    result renders an honest 'not enough grounds' note. The legal layers are in UKRAINIAN — the
    language of the court. Prose has leaked internal C-IDs stripped (_clean); all model/candidate
    text is HTML-escaped (untrusted — teza/chip/дії included)."""
    def e(text):                                                   # strip leaked C-IDs THEN escape
        return _html.escape(_clean(text))
    d = result.get("dovidka") or {}
    resolved = result.get("resolved") or {}
    out = ['<article class="pravova-dovidka" lang="uk">']
    if question:
        out.append(f'<header><h1>Правова довідка</h1><p class="question">{e(question)}</p></header>')
    if result.get("abstained"):
        # FIXED copy — the model's abstain prose is NEVER rendered (it leaked «кандидати»/C-IDs
        # to the user). Escaped defensively even though the text is ours, not the model's.
        steps = "".join(f"<li>{_html.escape(s)}</li>" for s in ABSTAIN_DIYI)
        out.append('<section class="abstain">'
                   f'<h2>Висновок</h2><p>{_html.escape(ABSTAIN_VYSNOVOK)}</p>'
                   f'<h2>Що робити</h2><ol>{steps}</ol>'
                   '</section></article>')
        return "\n".join(out)
    if d.get("vysnovok"):
        out.append(f'<section class="vysnovok"><h2>Висновок</h2><p>{e(d["vysnovok"])}</p></section>')
    if d.get("diyi"):
        steps = "".join(f"<li>{e(s)}</li>" for s in d["diyi"])
        out.append(f'<section class="diyi"><h2>Що робити</h2><ol>{steps}</ol></section>')
    if d.get("obgruntuvannya"):
        blocks = []
        for item in d["obgruntuvannya"]:
            chips = "".join(f'<span class="cite-chip">{e(resolved.get(cid, cid))}</span>'
                            for cid in item.get("citations") or [])
            blocks.append(f'<div class="teza"><p>{e(item.get("teza", ""))}</p>'
                          f'<div class="cites">{chips}</div></div>')
        out.append('<section class="obgruntuvannya"><h2>Правове обґрунтування</h2>'
                   + "".join(blocks) + "</section>")
    out.append("</article>")
    return "\n".join(out)


def _trace_dir(subdir: str = "t12") -> Path:
    base = os.getenv("DATA_DIR") or str(Path(__file__).resolve().parents[2] / "data")
    d = Path(base) / "traces" / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_trace(result: dict, question: str, sysprompt: str = _SYSTEM, ts: str | None = None,
                subdir: str = "t12") -> Path:
    """Append one JSONL trace line to $DATA_DIR/traces/<subdir>/traces.jsonl (working traces are
    DATA, not git). Records sha1(sysprompt) + per-attempt request_ids + candidate ids + resolved +
    lint + dropped + abstain — enough for the two-pass replay gate (the replay MECHANIC lives with
    the evaluation harness). `subdir` selects the pool: 't12' = self-check runs and scripts;
    **'t14' = the API seam** — the seam MUST write a trace, otherwise its `trace_ref` is a DANGLING
    pointer.
    ⚠ the record CONTAINS THE QUESTION. For t12 that is reference/synthetic questions ONLY (a red
    line; never real user personal data). For the **t14 seam** this is a DEV persist, decided for
    the first live test (a strange dovidka must be re-openable); **prod retention + PII policy is a
    separate decision** — do not treat this as a precedent for a prod user-data store.
    ⚠ NB for that retention policy: on an **abstain with no attempts** the seam still writes a
    record (it carries the QUESTION) while the response's `trace_ref` is None — an ORPHAN record,
    unreachable by any handle. The contract and the red line are NOT violated, but the pool
    accumulates questions that nothing addresses: retention MUST cover them, not just
    handle-reachable rows."""
    rec = {"t": ts or datetime.now(timezone.utc).isoformat(), "question": question,
           "sha1_sys": hashlib.sha1(sysprompt.encode("utf-8")).hexdigest(),
           "route": result.get("route"), "abstained": result.get("abstained"),
           # The model's abstain prose is no longer shown to the user → it MUST survive here,
           # otherwise the reason for an abstain becomes unrecoverable.
           "abstain_reason": result.get("abstain_reason"),
           "model_vysnovok": (result.get("dovidka") or {}).get("vysnovok"),
           "candidate_ids": [c["id"] for c in result.get("candidates", [])],
           "resolved": result.get("resolved"), "lint": result.get("lint"),
           "dropped": result.get("dropped"), "attempts": result.get("attempts")}
    path = _trace_dir(subdir) / "traces.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    import json as _json

    from pipelines.db import connect
    q = sys.argv[1] if len(sys.argv) > 1 else "Як оскаржити постанову ТЦК у справі про адмінправопорушення?"
    with connect() as conn:
        res = generate(conn, q)
    print(_json.dumps({"question": q, "route": res["route"], "abstained": res["abstained"],
                       "resolved": res["resolved"], "dovidka": res["dovidka"],
                       "attempts": [{k: a[k] for k in ("request_id", "invalid_ids", "abstain")}
                                    for a in res["attempts"]]}, ensure_ascii=False, indent=2))
