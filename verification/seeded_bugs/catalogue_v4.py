"""Fourth seeded-bug catalogue (v4): twenty realistic defects plus one canary, written by an agent
that saw only a copy of the source code and documentation, without tests, CI, verification code,
agent rules or git history, and that ran nothing but a checker of its own edits. Same rules as the
other catalogues: exact find->replace edits, each find occurring exactly once, one import-time
canary. Chosen by domain realism and consequence, never tuned to a measured result.
"""

from __future__ import annotations

from verification.seeded_bugs.catalogue import Bug, Edit

BUGS: tuple[Bug, ...] = (
    Bug("W00", "canary", "Import-time crash in pipelines.rag.retrieval",
        "Not a realistic bug: it proves that the runner applies edits and that the gates see "
        "them.",
        (Edit("pipelines/rag/retrieval.py",
              'CHANNELS = ("dense", "fts", "lemma")\n',
              'raise RuntimeError("seeded canary")\nCHANNELS = ("dense", "fts", "lemma")\n'),),
        canary=True),

    Bug("W01", "retrieval",
        "Scope gate drops the in_force_from bound: editions not yet in force are served",
        "Chasing empty answers for questions with a historical as_of (the v0 corpus holds only "
        "current editions, in force since 2025-2026), an agent relaxes scope_clause to 'not "
        "expired on as_of'. Every channel and the exact route share the clause, so an edition "
        "that entered into force after as_of is served as the law of that date, and a scheduled "
        "future edition passes as today's law.",
        (Edit("pipelines/rag/retrieval.py",
              '    return (f"{p}in_force_from <= {aod} "\n'
              '            f"AND ({p}in_force_to IS NULL OR {p}in_force_to >= {aod})")',
              '    return f"({p}in_force_to IS NULL OR {p}in_force_to >= {aod})"'),)),

    Bug("W02", "retrieval",
        "Exact-lookup regex drops superscript suffixes: article 210-1 is served as article 210",
        "An agent fixing article ranges such as 'articles 287-289', which _ART_RE read as the "
        "non-existent article 287-289, removes the hyphenated suffix from the pattern. Genuine "
        "superscript articles lose it too: a question about article 210-1 of the Code of "
        "Administrative Offences (the mobilisation-law fine) gets article 210 (military "
        "registration) as its deterministic, never-reranked first candidate.",
        (Edit("pipelines/rag/retrieval.py",
              r'_ART_RE = re.compile(r"\b(?:статт\w*|ст)\.?\s*(\d+(?:-\d+)?)", '
              r're.IGNORECASE)',
              r'_ART_RE = re.compile(r"\b(?:статт\w*|ст)\.?\s*(\d+)", re.IGNORECASE)'),)),

    Bug("W03", "retrieval",
        "Exact route binds an article to the act on its left even when two acts are named",
        "So that 'in the procedure code, article 47 and article 49' (act named first) stops "
        "dropping both articles, an agent lets any article with no act to its right fall back to "
        "the nearest act on the left and deletes the lone-citation guard. A question naming "
        "article 47 of that code and article 15 of a fishing law outside the corpus now gets "
        "article 15 of the procedure code as a deterministic top candidate.",
        (Edit("pipelines/rag/retrieval.py",
              '    distinct_acts = {n for _p, n in mentions}\n'
              '    lone = len(arts) == 1 and len(distinct_acts) == 1'
              '     # unambiguous single citation\n',
              ''),
         Edit("pipelines/rag/retrieval.py",
              '        elif lone:\n'
              '            nreg = next(iter(distinct_acts))',
              '        elif mentions:\n'
              '            nreg = max(mentions)[1]'))),

    Bug("W04", "citation gate",
        "Citation gate accepts a dovidka that also cites IDs outside the candidate set",
        "To cut regenerations and abstains, an agent accepts a dovidka as soon as one cited ID "
        "resolves, assuming the resolver just drops the invalid ones. It does not: render_dovidka "
        "falls back to the raw cited string, so an out-of-set ID or a free-text article reference "
        "the model put into citations reaches the user as a citation chip, while the harness "
        "sees only resolved IDs and keeps reporting zero hallucinations.",
        (Edit("pipelines/rag/generate.py",
              '        problem = None\n        if invalid:',
              '        problem = None\n        if invalid and not resolved:'),)),

    Bug("W05", "candidates",
        "Candidate dedup groups by article number alone, across different acts",
        "Simplifying dedup_candidates, an agent reads the unused _act loop variable as a sign "
        "that the act half of the grouping key is dead weight and keys groups by the article "
        "stem. Same-numbered articles of different acts (the documented 78 cross-act collisions "
        "of the 'article 5' kind) now share a group: when one act's article container is "
        "present, the other act's article is subsumed and silently leaves the candidate set, "
        "even when it is the gold norm.",
        (Edit("pipelines/rag/generate.py",
              '        groups.setdefault((h["act"], stem), []).append((i, h))',
              '        groups.setdefault(stem, []).append((i, h))'),
         Edit("pipelines/rag/generate.py",
              '    for (_act, stem), members in groups.items():',
              '    for stem, members in groups.items():'))),

    Bug("W06", "context budget",
        "Context budget truncates the candidate that overflows instead of dropping it",
        "To use the context better, an agent fills what is left of the 10 000-token budget with "
        "the head of the first candidate that does not fit, instead of stopping there. The model "
        "then reads a statute text cut mid-sentence, so an exception or condition at the end of "
        "the article can vanish while the article is still cited as a whole, and the dropped "
        "report lists nothing because the truncated candidate counts as kept.",
        (Edit("pipelines/rag/generate.py",
              '        if out and used + nt > max_tokens:\n            break\n',
              '        if out and used + nt > max_tokens:\n'
              '            room = max_tokens - used                   # fill what is left\n'
              '            if room > 0:\n'
              '                out.append({**c, "text": c["text"]'
              '[:len(c["text"]) * room // nt]})\n'
              '            break\n'),)),

    Bug("W07", "data governance",
        "USER_DATA tripwire lets non-text message parts through unscanned",
        "After the guard refused a request that carried an attached image or file part, an agent "
        "makes _message_texts skip parts it cannot read instead of refusing. The tripwire is no "
        "longer fail-closed: an image of a user's document, or a part that holds marked user "
        "text under a key other than 'text', now goes to DeepSeek, an external model with no "
        "zero retention that trains on its inputs.",
        (Edit("ml/llm_client.py",
              '                raise ValueError(\n'
              '                    "DeepSeek: message content part is not inspectable text "\n'
              '                    "(image/binary/unknown) — refusing (cannot verify it is '
              'PII-free).")',
              '                continue   # image/file part: no text to scan, let it through'),)),

    Bug("W08", "api",
        "API server binds to every network interface instead of 127.0.0.1",
        "To reach the dev API from the dev-shell container or a phone on the LAN, an agent sets "
        "the uvicorn host to 0.0.0.0. The endpoint has no auth and no rate limit, spends the "
        "paid DeepSeek key on every call and writes each question to the trace pool, and it is "
        "now open to the whole network, against the documented localhost-only red line.",
        (Edit("api/main.py",
              '    uvicorn.run(app, host="127.0.0.1", port=8000)',
              '    uvicorn.run(app, host="0.0.0.0", port=8000)'),)),

    Bug("W09", "evaluation",
        "Retrieval eval counts any article whose number merely starts with the gold number",
        "An agent simplifies the hit test in _gold_rank (the exact path, or a path under it) to "
        "a bare startswith(art). Gold article 210 is now found by article 210-1, gold article 1 "
        "by articles 10 to 19 and 100 to 199 of the same act, so recall@k, p@1 and MRR@k in the "
        "published per-class tables are inflated by near-miss articles.",
        (Edit("eval/retrieval_eval.py",
              '        if any(h["act"] == act and (h["unit_path"] == art or '
              'h["unit_path"].startswith(art + "/"))',
              '        if any(h["act"] == act and h["unit_path"].startswith(art)'),)),

    Bug("W10", "evaluation",
        "Harness scores an abstained answer that still lists citations as a normal answer",
        "Seeing the model set abstain=true while still citing the gold article, an agent decides "
        "such answers deserve credit and treats only citation-free abstains as abstains. The "
        "reader of an abstained dovidka sees no citation at all (render_dovidka prints only the "
        "fixed abstain note), yet the harness now scores it correct and not as an abstain, which "
        "inflates the correct count and hides the abstain rate.",
        (Edit("eval/harness.py",
              '    if mf["abstain"]:',
              '    if mf["abstain"] and not mf["cited"]:'),)),

    Bug("W11", "evaluation",
        "Replay-noise gate no longer turns RED on a gold-citation flip by itself",
        "Reasoning that every gold flip is also a set flip and is therefore already counted in "
        "the thresholded rate, an agent reduces the RED condition to the set-flip rate. With the "
        "0.45 threshold, one or two gold flips among 29 questions now pass as REPLAY [GREEN] "
        "with exit 0, although the gate treats a gold flip as a hard incident at any count.",
        (Edit("eval/harness.py",
              '            red = noise["gold_flips"] > 0 or '
              'noise["set_flip_rate"] > NOISE_FLIP_THRESHOLD',
              '            red = noise["set_flip_rate"] > NOISE_FLIP_THRESHOLD'
              '   # a gold flip is a set flip too'),)),

    Bug("W12", "exit codes",
        "fetch_cards exits 0 when card fetches failed but the editions floor is met",
        "De-flaking the daily card job, an agent stops failing the run over individual card "
        "errors once the cumulative editions floor (100) is met, since the failures are printed "
        "anyway. An act whose card could not be fetched silently misses its new editions while "
        "cron and the orchestrator see a green exit: the 'exit 0 while errors happened' pattern "
        "the exit-code convention exists to forbid.",
        (Edit("pipelines/rada/fetch_cards.py",
              '    if failed_acts or not floor_ok:\n        return exitcodes.FAIL',
              '    if not floor_ok:\n        return exitcodes.FAIL'),)),

    Bug("W13", "exit codes",
        "Unclosed amendment quote at end of file is demoted to a warning; the parse exits 0",
        "To unblock the nightly chain after one edition tripped the unclosed-quote tripwire, an "
        "agent removes the failing summary and the return 1 and keeps only the printed warning. "
        "The parse now reports failed=0 and exits 0 although every structural heading after the "
        "unclosed quote was suppressed, so the chunker builds that act from units whose tail was "
        "silently merged into one.",
        (Edit("pipelines/rada/parse_structure.py",
              '        _summary.emit(ok=grand_eds - len(quote_eof_bad), '
              'failed=len(quote_eof_bad), nbytes=0)\n'
              '        return 1\n',
              '        # warning only: one bad edition must not block the nightly chain\n'),)),

    Bug("W14", "collection",
        "Rada HTTP helper follows redirects by default, which disables the routing guard",
        "After a RadaRoutingError on a legitimate redirect, an agent flips the follow_redirects "
        "default of get() to True, as in the httpx examples. A lost-User-Agent or anti-DDoS 302 "
        "to zakon.rada.gov.ua is now followed to an HTML page with status 200: fetch_texts saves "
        "that page as the edition text (and its size>0 skip keeps it forever), and the parser "
        "turns it into garbage units.",
        (Edit("pipelines/checks/_common.py",
              '    follow_redirects: bool = False,',
              '    follow_redirects: bool = True,'),)),

    Bug("W15", "collection",
        "Edition texts are fetched from Rada without the polite pause",
        "To speed up the 121-edition history of the Code of Administrative Offences, an agent "
        "calls get(url, polite=False) in fetch_txt, reasoning that the daily byte budget already "
        "meters Rada. A byte cap does not limit the request rate: editions are now requested "
        "back to back against Rada's 5-7 s pause and 60-per-minute terms, which is what triggers "
        "its anti-DDoS IP block and stalls every Rada collector for hours.",
        (Edit("pipelines/rada/fetch_texts.py",
              '        r = get(url)\n        status = r.status_code',
              '        r = get(url, polite=False)   # the daily byte budget already meters Rada\n'
              '        status = r.status_code'),)),

    Bug("W16", "parsing",
        "Article text no longer contains the article heading",
        "Seeing the heading stored both as the title and inside the text, an agent builds an "
        "article's text from its body alone. Headings such as 'Time limits for imposing an "
        "administrative penalty' disappear from chunk text and so from all three retrieval "
        "channels, and single-line articles of older editions (the whole article written on its "
        "'Article N.' line) are stored with an empty text.",
        (Edit("pipelines/rada/parse_structure.py",
              r'            art_text = _clean("\n".join([m.group(2), *body]))',
              r'            art_text = _clean("\n".join(body))   # the heading is the title'),)),

    Bug("W17", "parsing",
        "Duplicate unit paths are suffixed in document order: a repeal husk keeps the live path",
        "An agent simplifies _dedupe to suffix duplicate paths in plain document order. In the "
        "Code of Administrative Offences the empty husk of the repealed article 163 keeps the "
        "canonical path while the live, re-issued article 163 moves to the '~2' artefact path: "
        "the exact route finds nothing for 'article 163' (the husk has no text and is never "
        "chunked) and the live article is cited as article '163~2'.",
        (Edit("pipelines/rada/parse_structure.py",
              '        group.sort(key=lambda u: (not u.text, u.ordinal))'
              '   # substantive first, then order',
              '        group.sort(key=lambda u: u.ordinal)   # plain document order'),)),

    Bug("W18", "chunking",
        "Citations of approved documents drop their block ordinal and collide",
        "Polishing user-facing citation chips, an agent renders an approved document by its "
        "title alone and drops the '(zatv. N)' suffix as internal jargon. Resolutions "
        "560-2024-p and 76-2023-p title both of their approved documents 'PROCEDURE', so 46 "
        "chunks share 23 citation strings again and a reader cannot tell which procedure a cited "
        "point belongs to.",
        (Edit("pipelines/rada/chunk.py",
              '            parts.append(f"{block_title} (затв. {num})" if block_title '
              'else f"затв. {num}")',
              '            parts.append(block_title or f"затв. {num}")'),)),

    Bug("W19", "freshness",
        "Freshness matcher no longer recognises the canonical nreg of the mobilisation law",
        "An agent rewrites seed_alias_map as a one-line dict comprehension, not seeing why each "
        "canonical nreg also maps to itself. Rada's recent-changes feed lists acts by canonical "
        "nreg, so 3633-20 (the mobilisation law, stored as 3633-IX) never matches again: the "
        "daily probe reports no change for the product's central law, and only the weekly card "
        "backstop can still notice a new edition.",
        (Edit("pipelines/freshness/probe.py",
              '    amap: dict[str, str] = {}\n'
              '    for key in SEED_ACTS:\n'
              '        c = canon.get(key, key)\n'
              '        amap[key] = c\n'
              '        amap[c] = c\n'
              '    return amap',
              '    return {key: canon.get(key, key) for key in SEED_ACTS}'),)),

    Bug("W20", "ledger",
        "Units ledger flags only editions that shrank; growth in a known edition passes",
        "After a parser fix legitimately added units to known editions, an agent quiets the "
        "ledger comparison by treating growth as expected and flagging only editions whose "
        "count fell. An injection into a known edition, or a reparse that duplicates units, now "
        "passes the gate: one of the two faults the ledger exists to expose while totals stay "
        "above their floors.",
        (Edit("pipelines/units_ledger.py",
              'for k, v in ledger_entries.items() if live_entries.get(k) != v}',
              'for k, v in ledger_entries.items() if live_entries.get(k, 0) < v}'),)),
)
