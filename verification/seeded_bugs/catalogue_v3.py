"""Third seeded-bug catalogue (v3): twenty realistic defects plus one canary, written by an agent
that saw only a copy of the source code and documentation, without tests, CI, verification code,
agent rules or git history, and that ran no gate, test suite or harness. Same rules as the other
catalogues: exact find->replace edits, each find occurring exactly once, one import-time canary.
Chosen by domain realism and consequence, never tuned to a measured result.
"""

from __future__ import annotations

from verification.seeded_bugs.catalogue import Bug, Edit

BUGS: tuple[Bug, ...] = (
    Bug("V00", "canary", "Import-time crash in pipelines/rag/retrieval.py",
        "Not a realistic bug: it proves that the runner applies edits and that the gates see them.",
        (Edit("pipelines/rag/retrieval.py",
              "sys.path.insert(0, str(Path(__file__).resolve().parents[2]))",
              'raise RuntimeError("seeded canary")\n'
              "sys.path.insert(0, str(Path(__file__).resolve().parents[2]))"),),
        canary=True),

    Bug("V01", "retrieval", "Candidate channels ignore the as_of date and gate on today",
        "Tidying the channel dispatch in _run_channel into keyword style, an agent passes only "
        "k=topn and drops the positional as_of, which dense(), fts() and lemma() default to "
        "None. Every channel candidate is then scope-gated on today's Kyiv date instead of the "
        "date the caller asked about, so a question with as_of set (the API accepts one) is "
        "answered from the editions in force today; only the exact route still honours the date.",
        (Edit("pipelines/rag/retrieval.py",
              "        return fn(conn, query_text, as_of, k=topn)",
              "        return fn(conn, query_text, k=topn)"),)),

    Bug("V02", "retrieval", "RRF fusion returns the lowest-scoring candidates first",
        "Adding a deterministic tie-break to the RRF sort (equal scores were ordered by channel "
        "insertion, which made replays flip), an agent negates the score in the sort key but "
        "leaves reverse=True in place. The fused list now comes out worst-first: hybrid() keeps "
        "the bottom of the pool, the reranker only ever reorders the weakest candidates, and "
        "with the reranker down the inverted order is served as the fallback ranking.",
        (Edit("pipelines/rag/retrieval.py",
              "sorted(scores.items(), key=lambda kv: kv[1], reverse=True)",
              "sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]), reverse=True)"),)),

    Bug("V03", "retrieval", "Code abbreviations match case-insensitively on the raw question",
        "A user typed the Code of Administrative Procedure's abbreviation in lower case and the "
        "exact route stayed silent, so an agent makes the abbreviation check case-insensitive "
        "like the title match. In lower case that abbreviation is also an ordinary word (the "
        "genitive plural of 'cash desk'), so a question about working without cash desks that "
        "names an article number is bound to that code, and the code's article is served as the "
        "deterministic first candidate: a citation to the wrong act.",
        (Edit("pipelines/rag/retrieval.py",
              r'if re.search(rf"(?<!\w){re.escape(abbr)}(?!\w)", query):',
              r'if re.search(rf"(?<!\w){re.escape(abbr)}(?!\w)", query, re.IGNORECASE):'),)),

    Bug("V04", "citation gate", "Out-of-set citation IDs pass when one other ID resolves",
        "To save a paid regeneration when the model adds one stray ID next to valid ones, an "
        "agent rejects a dovidka only when nothing resolves. A thesis backed only by an ID "
        "outside the candidate set, or by a free-text article reference the model wrote into "
        "citations, now reaches the user: render_dovidka prints the unresolved string itself as "
        "a citation chip, and the harness hallucination probe stays at 0 because it only looks "
        "at resolved IDs.",
        (Edit("pipelines/rag/generate.py",
              "        if invalid:",
              "        if invalid and not resolved:"),)),

    Bug("V05", "citation gate", "A dovidka without legal theses is accepted with no citation",
        "A purely practical answer (a conclusion and steps, no theses) was regenerated twice and "
        "then abstained, so an agent limits the mandatory-citation rule to dovidkas that carry "
        "theses. The model can now dodge the gate by leaving obgruntuvannya empty: a conclusion "
        "and action steps about the law, drawn from its own memory and backed by no candidate, "
        "are returned as a valid, non-abstained answer.",
        (Edit("pipelines/rag/generate.py",
              "        elif not resolved:",
              '        elif not resolved and dovidka.get("obgruntuvannya"):'),)),

    Bug("V06", "context budget", "The last candidate is truncated to fill the context budget",
        "Seeing thousands of budget tokens left unused whenever a large article did not fit, an "
        "agent fills the remainder with the head of that candidate instead of dropping it whole. "
        "The model now reads a norm cut mid-sentence (often before its exceptions) under a "
        "citation that names the whole unit, and the dropped report says nothing was cut, "
        "because the truncated candidate counts as kept.",
        (Edit("pipelines/rag/generate.py",
              "        if out and used + nt > max_tokens:\n"
              "            break\n",
              "        if out and used + nt > max_tokens:\n"
              "            room = max_tokens - used\n"
              "            if room >= 500:   # fill the leftover budget\n"
              "                out.append({**c, "
              '"text": c["text"][:room * 4], "n_tokens": room})\n'
              "            break\n"),)),

    Bug("V07", "data governance", "The USER_DATA tripwire is logged and skipped on generation",
        "A regeneration turn crashed on a message part the fail-closed walker could not inspect, "
        "so an agent wraps the guard in call_tool_deepseek to log the ValueError and carry on. "
        "The USER_DATA tripwire raises the same ValueError, so a prompt carrying the user-data "
        "sentinel is now logged and sent anyway to an external model with no zero-data "
        "retention: the seatbelt no longer holds on the generation path.",
        (Edit("ml/llm_client.py",
              "    _guard_deepseek(messages)\n"
              "    model = model or DEEPSEEK_MODEL\n"
              '    params = _strictify_schema(copy.deepcopy(tool["parameters"]))\n',
              "    try:\n"
              "        _guard_deepseek(messages)\n"
              "    except ValueError as exc:   # a stray part must not kill a retry\n"
              '        print(f"[deepseek] payload check skipped: {exc}")\n'
              "    model = model or DEEPSEEK_MODEL\n"
              '    params = _strictify_schema(copy.deepcopy(tool["parameters"]))\n'),)),

    Bug("V08", "api", "A generation-provider outage is answered as a 200 abstain",
        "To stop one transient DeepSeek timeout from failing the whole request, an agent catches "
        "provider errors in the generation loop and lets it fall through to the abstain. An "
        "outage, a missing API key or a truncated tool call now comes back as HTTP 200 with the "
        "fixed 'no grounds in the available norms' copy instead of 503 generation_unavailable: "
        "users are told the law gives no answer, monitoring sees no errors, and a live harness "
        "run scores the outage as abstains rather than errors.",
        (Edit("pipelines/rag/generate.py",
              "        r = call_tool_deepseek(messages, CITATION_TOOL, temperature=0.0, "
              "max_tokens=3000)\n",
              "        try:\n"
              "            r = call_tool_deepseek(messages, CITATION_TOOL, temperature=0.0, "
              "max_tokens=3000)\n"
              "        except Exception:   # a provider hiccup ends in the honest abstain below\n"
              "            break\n"),)),

    Bug("V09", "api", "The API seam binds to every network interface",
        "The dev-shell running in a docker-compose container could not reach the API on "
        "127.0.0.1, so an agent binds uvicorn to 0.0.0.0 and leaves the 'localhost ONLY' "
        "comment in place. The seam has no auth and no rate limit, spends the paid DeepSeek key "
        "on every request and writes every question to DATA_DIR, and it is now reachable from "
        "any host on the network.",
        (Edit("api/main.py",
              'host="127.0.0.1", port=8000)',
              'host="0.0.0.0", port=8000)'),)),

    Bug("V10", "evaluation", "Retrieval eval counts neighbouring article numbers as gold hits",
        "Simplifying the article match in _gold_rank to a single startswith, an agent drops the "
        "exact-or-slash rule. Gold article 21 now counts article 210, 211 or 21-1 of the same "
        "act as a hit, so recall@k, p@1 and MRR are inflated exactly on the questions where "
        "retrieval picked a neighbouring article, and the published per-class table and any "
        "calibration built on it become misleading.",
        (Edit("eval/retrieval_eval.py",
              'h["act"] == act and (h["unit_path"] == art '
              'or h["unit_path"].startswith(art + "/"))',
              'h["act"] == act and h["unit_path"].startswith(art)'),)),

    Bug("V11", "evaluation", "Golden cases that raise are skipped and the gate stays green",
        "Mirroring score()'s per-row catch, an agent wraps the golden calls in _run_safe and "
        "skips a case whose call raised. When the live pipeline is down every reference question "
        "lands in errors and every golden case is skipped, so --mode gate prints GREEN and "
        "exits 0 on a run that scored nothing; a regression that makes generate() raise on a "
        "golden question is equally invisible.",
        (Edit("eval/harness.py",
              '        result = run_fn({"question": c["question"], "expected": '
              '_golden_expected(c), "as_of": None})\n',
              '        result, err = _run_safe(run_fn, {"question": c["question"],\n'
              '                                         "expected": _golden_expected(c), '
              '"as_of": None})\n'
              "        if err:   # harness hygiene: one failing golden call must not crash\n"
              "            continue\n"),)),

    Bug("V12", "exit codes", "worst() takes the numeric maximum, so FAIL plus SKIP reads SKIP",
        "Reading the severity table as a redundant indirection, an agent reduces worst() to "
        "max(codes). The numeric order is OK 0, FAIL 1, SKIP 2, STALE 3, so a batch with one "
        "failed collector and one budget-deferred collector reduces to SKIP, and FAIL plus "
        "STALE to STALE: the overall batch code reports a planned defer where a collector "
        "actually failed, the exact masquerade the module warns about.",
        (Edit("pipelines/exitcodes.py",
              "    return max(codes, key=lambda c: _SEVERITY.get(c, 3), default=OK)",
              "    return max(codes, default=OK)"),)),

    Bug("V13", "exit codes", "An unclosed amendment quote no longer fails the parse run",
        "The orchestrated daily parse kept going red on one old edition, so an agent demotes the "
        "unclosed-quote check to a warning: the message is still printed, but the run falls "
        "through to the normal summary (failed=0) and exit 0. Editions whose structural tail "
        "was suppressed and merged into one unit are written and journaled as fully parsed, and "
        "the only honest signal that their units are untrustworthy is gone.",
        (Edit("pipelines/rada/parse_structure.py",
              "        _summary.emit(ok=grand_eds - len(quote_eof_bad), "
              "failed=len(quote_eof_bad), nbytes=0)\n"
              "        return 1\n",
              "        # a warning, not a red run: the units are written, and one old edition\n"
              "        # must not fail the whole daily parse\n"),)),

    Bug("V14", "collection", "fetch_texts skips the polite pause between Rada requests",
        "Backfilling 121 editions of the Code of Administrative Offences took hours because of "
        "the 6-second polite pause, and an agent reasons that the daily byte budget already "
        "meters Rada, so it passes polite=False. The budget caps bytes, not request rate: "
        "edition downloads now go out back to back, far above the host's published per-minute "
        "terms, which is exactly the traffic that earns the collector's IP a multi-hour "
        "anti-DDoS block.",
        (Edit("pipelines/rada/fetch_texts.py",
              "        r = get(url)\n",
              "        r = get(url, polite=False)   # the byte budget meters Rada\n"),)),

    Bug("V15", "freshness", "The probe's previous signal can be a failed probe's NULL",
        "Simplifying _last_signal to 'the latest row for this source', an agent drops the "
        "signal_value IS NOT NULL filter. After any failed probe (a Rada 403 writes a NULL "
        "signal) the next real signal is compared against NULL, changed stays False and the new "
        "baseline silently absorbs the move: a new edition of a seed act that lands around a "
        "failed probe never turns the source yellow, and the corpus keeps serving the "
        "superseded edition as current law.",
        (Edit("pipelines/freshness/probe.py",
              '"WHERE source_id=%s AND signal_value IS NOT NULL "',
              '"WHERE source_id=%s "'),)),

    Bug("V16", "freshness", "A budget-truncated backstop run writes a signal over a subset",
        "To keep the backstop signal from going NULL whenever the Rada budget deferred a card, "
        "an agent hashes whatever acts were checked. A partial run now writes a non-NULL signal "
        "over a subset: it flips changed to a false yellow against the full-set baseline, and "
        "because the 7-day gate counts only non-NULL runs, the acts that were never fetched "
        "count as verified and are not re-checked for a week.",
        (Edit("pipelines/freshness/rada_backstop.py",
              "    if results and complete:",
              "    if results:"),)),

    Bug("V17", "parsing", "Duplicate unit paths go to document order and the repealed husk wins",
        "Making _dedupe 'plainly deterministic', an agent sorts each collision group by ordinal "
        "only. The Code of Administrative Offences carries both the empty repealed heading of "
        "article 163 and the live, re-issued article 163: the husk now keeps the canonical path "
        "(and, being empty, never becomes a chunk) while the live offence article moves to the "
        "dedup artefact path suffixed ~2, which the exact route never looks up and which users "
        "then see inside its citation string.",
        (Edit("pipelines/rada/parse_structure.py",
              "group.sort(key=lambda u: (not u.text, u.ordinal))",
              "group.sort(key=lambda u: u.ordinal)"),)),

    Bug("V18", "parsing", "The amendment-marker pattern turns greedy and deletes legal text",
        "A marker nested inside another marker left a stray fragment and brace in the clean "
        "text, so an agent widens MARKER_RE from a brace-free body to .* (the pattern already "
        "has DOTALL). The match is now greedy across lines: _clean deletes everything from a "
        "unit's first amendment note to its last, so an article amended twice silently loses "
        "all the legal text between the two notes, which is stored as one giant marker instead.",
        (Edit("pipelines/rada/parse_structure.py",
              r'MARKER_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)',
              r'MARKER_RE = re.compile(r"\{.*\}", re.DOTALL)   # nested markers too'),)),

    Bug("V19", "ledger", "The units ledger no longer flags units injected into an edition",
        "After a reparse that legitimately added units to a known edition turned the data gate "
        "red, an agent narrows the ledger diff to shrinkage only. An injection into a known "
        "edition, such as a reparse that turns quoted amendment headings into phantom host "
        "articles, now passes silently while the totals stay above their floors, which is half "
        "of what the ledger exists to catch.",
        (Edit("pipelines/units_ledger.py",
              "if live_entries.get(k) != v}",
              "if live_entries.get(k, 0) < v}"),)),

    Bug("V20", "chunking", "Approved-document citations drop the block ordinal",
        "Tidying citation strings (a reviewer found the '(zatv. 1)' suffix noisy), an agent "
        "renders only the block title when there is one. Two Cabinet resolutions in the "
        "perimeter title both their first and second approved blocks with the same word "
        "(PORIADOK, 'procedure'), so points of two different approved procedures now share one "
        "citation string, and the user can no longer tell which document a cited point is in.",
        (Edit("pipelines/rada/chunk.py",
              'parts.append(f"{block_title} (затв. {num})" if block_title else f"затв. {num}")',
              'parts.append(block_title if block_title else f"затв. {num}")'),)),
)
