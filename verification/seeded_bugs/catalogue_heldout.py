"""Held-out seeded-bug catalogue: twenty realistic defects plus one canary, written AFTER the
gap-closing tests were added, by an agent that did not open tests/, verification/ or the first
catalogue and did not run any gate, suite or harness. Same rules as catalogue.py — exact
find->replace edits, each find occurring exactly once, one import-time canary — and chosen only by
domain realism and consequence, never tuned to any measured result.
"""

from __future__ import annotations

from verification.seeded_bugs.catalogue import Bug, Edit

BUGS: tuple[Bug, ...] = (
    Bug("H00", "canary", "Import-time crash in the generation module",
        "Not a realistic bug: it proves that the runner applies edits and that the gates see them.",
        (Edit("pipelines/rag/generate.py", "MAX_RETRIES = 2 ",
              'raise RuntimeError("seeded canary")\nMAX_RETRIES = 2 '),),
        canary=True),

    Bug("H01", "retrieval", "Temporal scope gate inverted: serves editions not yet in force",
        "Tidying the scope predicate, an agent 'corrects' the date direction to in_force_from >= "
        "as_of ('in force from this date onward'), inverting the gate so the current edition is "
        "dropped and a future/not-yet-in-force edition is served and cited.",
        (Edit("pipelines/rag/retrieval.py",
              '    return (f"{p}in_force_from <= {aod} "',
              '    return (f"{p}in_force_from >= {aod} "'),)),

    Bug("H02", "retrieval", "Exact-lookup drops the natural-order re-sort of an article's leaves",
        "An agent deems the in-Python natkey sort redundant because the SQL already has ORDER BY "
        "unit_path, and removes it — reintroducing the lexicographic page the comment warns about "
        "(ст.N/п.10 before п.2; parts cut before the cap).",
        (Edit("pipelines/rag/retrieval.py",
              "sorted(cur.fetchall(), key=lambda r: natkey(r[2]))[:limit]",
              "cur.fetchall()[:limit]"),)),

    Bug("H03", "retrieval", "Reranker ordering reversed: least-relevant candidates ranked first",
        "While refactoring the rerank step an agent flips reverse=True to reverse=False, so the "
        "cross-encoder orders candidates worst-first and the gold article is pushed down or out of "
        "the top-k handed to generation.",
        (Edit("pipelines/rag/retrieval.py",
              'key=lambda h: h["rerank_score"], reverse=True',
              'key=lambda h: h["rerank_score"], reverse=False'),)),

    Bug("H04", "context budget", "Context budget skips an over-budget candidate instead of tail-dropping",
        "An agent 'packs the budget better' by changing break to continue, so a high-ranked large "
        "candidate is silently skipped while smaller lower-ranked ones fill in — C1..Ck are no "
        "longer the contiguous top set, and the dropped-report (which assumes a prefix) misreports "
        "what was cut.",
        (Edit("pipelines/rag/generate.py",
              "        if out and used + nt > max_tokens:\n"
              "            break\n"
              "        out.append(c)",
              "        if out and used + nt > max_tokens:\n"
              "            continue\n"
              "        out.append(c)"),)),

    Bug("H05", "citation gate", "Citation gate tolerates an out-of-set id when any valid id is cited",
        "Aiming to 'not waste a good answer', an agent makes the out-of-set rejection conditional "
        "on there being no valid citation at all (if invalid and not resolved), so a dovidka that "
        "mixes a real candidate with a fabricated C-id is accepted and served instead of being "
        "regenerated — the code no longer arbitrates every id.",
        (Edit("pipelines/rag/generate.py",
              "        if invalid:                                                # ID outside the set → reject",
              "        if invalid and not resolved:                               # ID outside the set → reject"),)),

    Bug("H06", "data governance", "User-data tripwire requires ALL fragments to be marked",
        "Refactoring the guard, an agent reads 'all fragments must be clean' and writes all() "
        "where any() was meant, so the tripwire fires only when every fragment carries the "
        "sentinel — a message mixing open-data text with one marked user fragment now passes to the "
        "external model.",
        (Edit("ml/llm_client.py",
              '        if m.get("user_data") or any(\n'
              "                USER_DATA_SENTINEL in frag for frag in _message_texts(m)):",
              '        if m.get("user_data") or all(\n'
              "                USER_DATA_SENTINEL in frag for frag in _message_texts(m)):"),)),

    Bug("H07", "data governance", "String walker fails open on uninspectable values",
        "An agent makes the scanner 'robust' by returning [] for a type it cannot reduce to text "
        "instead of raising, so a bytes/set/custom-object leaf that could hide a marked fragment is "
        "no longer inspected — the fail-closed guarantee becomes fail-open and user data can slip "
        "past the tripwire.",
        (Edit("ml/llm_client.py",
              "    raise ValueError(\n"
              '        f"DeepSeek: uninspectable value of type {type(obj).__name__} in message — "\n'
              '        "refusing (cannot verify it is PII-free).")',
              "    return []"),)),

    Bug("H08", "api", "API binds to all interfaces instead of localhost",
        "An agent 'makes the dev server reachable' by switching the bind host to 0.0.0.0, exposing "
        "the no-auth, no-rate-limit generate endpoint (and its trace seam) beyond 127.0.0.1.",
        (Edit("api/main.py",
              '    uvicorn.run(app, host="127.0.0.1", port=8000)          # localhost ONLY (dev)',
              '    uvicorn.run(app, host="0.0.0.0", port=8000)          # localhost ONLY (dev)'),)),

    Bug("H09", "exit codes", "Batch exit-code reducer uses numeric max instead of severity",
        "An agent 'simplifies' worst() to a bare max(codes), so reduction follows numeric value "
        "(STALE=3 > SKIP=2 > FAIL=1) instead of severity — a batch containing a FAIL(1) and a "
        "SKIP(2) returns SKIP, the exact 'a failure masquerades as a skip' trap the module warns "
        "against.",
        (Edit("pipelines/exitcodes.py",
              "    return max(codes, key=lambda c: _SEVERITY.get(c, 3), default=OK)",
              "    return max(codes, default=OK)"),)),

    Bug("H10", "collection", "Politeness pause removed for the bulk court registry",
        "An agent 'speeds up the backfill' by setting od.reyestr pause_s back to 0.0, removing the "
        "inter-request pause that was tightened to 0.2 precisely to smooth the burst to ~5 rps — "
        "the per-host politeness limit is now exceeded.",
        (Edit("pipelines/politeness.py",
              '    "od.reyestr.court.gov.ua": {"pause_s": 0.2, "req_per_min": 300, "req_per_day": 300_000,',
              '    "od.reyestr.court.gov.ua": {"pause_s": 0.0, "req_per_min": 300, "req_per_day": 300_000,'),)),

    Bug("H11", "collection", "Rada daily byte cap inflated past the published limit",
        "An agent 'gives the collector headroom' and raises CAP_BYTES to 800 MB, breaking the "
        "self-cap that keeps the daily Rada download under the source's published 200 MB/day limit.",
        (Edit("pipelines/rada/budget.py",
              "CAP_BYTES = 180_000_000                     # decimal 180 MB (one convention everywhere)",
              "CAP_BYTES = 800_000_000                     # decimal 180 MB (one convention everywhere)"),)),

    Bug("H12", "collection", "Units ledger stops flagging deleted editions",
        "An agent adds a 'skip missing editions' guard to the ledger diff, so an edition that has "
        "vanished from the DB (a partial deletion or injection) is no longer reported as "
        "changed_or_deleted — the one check that catches a deletion above the count floors goes "
        "silent.",
        (Edit("pipelines/units_ledger.py",
              "               for k, v in ledger_entries.items() if live_entries.get(k) != v}",
              "               for k, v in ledger_entries.items() if k in live_entries and live_entries.get(k) != v}"),)),

    Bug("H13", "rendering", "Citation drops the block ordinal, colliding two approved documents",
        "An agent 'cleans up' the ЗАТВЕРДЖЕНО rendering, trusting the title alone and dropping the "
        "(затв. N) ordinal — so two blocks with the same title (e.g. both ПОРЯДОК in 560-2024-п) "
        "render one identical citation string, a collision that hollows the structural gate.",
        (Edit("pipelines/rada/chunk.py",
              '            parts.append(f"{block_title} (затв. {num})" if block_title else f"затв. {num}")',
              '            parts.append(f"{block_title}" if block_title else f"затв. {num}")'),)),

    Bug("H14", "parsing", "Duplicate-path dedup no longer prefers the substantive unit",
        "An agent 'simplifies' the dedup sort to document order, so an empty repeal husk keeps the "
        "canonical ст.N path and the live re-issued article is pushed onto ст.N~2 — retrieval then "
        "serves the empty husk as the article.",
        (Edit("pipelines/rada/parse_structure.py",
              "        group.sort(key=lambda u: (not u.text, u.ordinal))   # substantive first, then order",
              "        group.sort(key=lambda u: u.ordinal)   # substantive first, then order"),)),

    Bug("H15", "evaluation", "Gate no longer reds on a citation-gate breach",
        "An agent 'tidies' the gate condition and drops the hallucination leg, so a resolved id "
        "outside the candidate set — the structural breach the gate exists to catch — no longer "
        "turns --mode gate red.",
        (Edit("eval/harness.py",
              '        red = bool(a["hallucination"]) or bool(gr["mechanical_red"])',
              '        red = bool(gr["mechanical_red"])'),)),

    Bug("H16", "evaluation", "Recall hit-test prefix-matches, inflating recall",
        "An agent removes the '/' from the article prefix check as 'redundant', so ст.2 now matches "
        "ст.20, ст.23 and friends — a near-miss article is counted as a gold hit and recall@k / "
        "precision@1 read higher than reality.",
        (Edit("eval/retrieval_eval.py",
              'h["unit_path"].startswith(art + "/")',
              'h["unit_path"].startswith(art)'),)),

    Bug("H17", "evaluation", "Replay-noise threshold raised far above the measured floor",
        "Finding the replay gate 'too flaky', an agent bumps the set-flip threshold to 0.95, well "
        "above the measured 0.310 noise floor, so genuine temperature-0 instability no longer trips "
        "the two-pass replay red.",
        (Edit("eval/harness.py",
              "NOISE_FLIP_THRESHOLD = 0.45",
              "NOISE_FLIP_THRESHOLD = 0.95"),)),

    Bug("H18", "evaluation", "Retrieval-baseline regression downgraded to a non-fatal warning",
        "An agent 'stops the baseline from failing CI on churn' by returning 0 from the lost-gold "
        "branch, so a question that used to retrieve its gold norm and now does not is printed but "
        "no longer fails the regression check.",
        (Edit("eval/retrieval_baseline.py",
              '        print("REGRESSION [RED] — a question that used to retrieve its gold norm no longer does.")\n'
              "        return 1",
              '        print("REGRESSION [RED] — a question that used to retrieve its gold norm no longer does.")\n'
              "        return 0"),)),

    Bug("H19", "exit codes", "Reachability RED reported as a planned skip",
        "An agent 'reduces noise' from the reachability watcher by mapping RED to SKIP, so a "
        "genuine routing/migration anomaly (data.rada serving HTML instead of JSON) exits 2 and "
        "cron treats a real source breakage as a benign defer.",
        (Edit("pipelines/rada/reachability.py",
              "_EXIT = {GREEN: exitcodes.OK, YELLOW: exitcodes.SKIP, ERROR: exitcodes.SKIP, RED: exitcodes.FAIL}",
              "_EXIT = {GREEN: exitcodes.OK, YELLOW: exitcodes.SKIP, ERROR: exitcodes.SKIP, RED: exitcodes.SKIP}"),)),

    Bug("H20", "exit codes", "Card fetch exits OK despite fetch failures",
        "An agent decides the cumulative editions floor is enough and drops failed_acts from the "
        "exit condition, so swallowed per-card fetch failures exit 0 as long as the floor is "
        "already met — exit 0 while errors happened.",
        (Edit("pipelines/rada/fetch_cards.py",
              "    if failed_acts or not floor_ok:",
              "    if not floor_ok:"),)),
)
