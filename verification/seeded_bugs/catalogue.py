"""Seeded-bug catalogue: realistic defects, planted one at a time, to measure what the gates catch.

Every bug is the kind of change a coding agent makes while "fixing" or "simplifying" code: a
dropped check, an off-by-one, a flipped comparison, a swallowed signal, a test weakened until it
passes. Each edit is an exact find -> replace that must match the current code exactly once; when
the code moves on, the runner fails loudly instead of measuring a bug that no longer exists.

Rules the catalogue follows:
- it was written before the first measured run and is not tuned to the result: a miss stays in the
  catalogue as a documented gap;
- the report records the sha256 of this file, so every published number is tied to the catalogue
  that produced it;
- B00 is a canary (an import-time crash): the runner refuses to report if the canary is not caught;
- B26 is the one bug derived from a measurement: it plants B01 and then weakens exactly the tests
  that caught B01 in a probe run, the way an agent under pressure makes a suite green.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Edit:
    file: str
    find: str
    replace: str


@dataclass(frozen=True)
class Bug:
    id: str
    area: str
    title: str
    story: str                      # how an agent plausibly arrives at this change
    edits: tuple[Edit, ...]
    canary: bool = False


_GEN = "pipelines/rag/generate.py"
_RET = "pipelines/rag/retrieval.py"
_LLM = "ml/llm_client.py"
_EXIT = "pipelines/exitcodes.py"
_KSU = "pipelines/ksu/snapshot.py"
_API = "api/main.py"
_HARNESS = "eval/harness.py"
_RETEVAL = "eval/retrieval_eval.py"
_GEN_TESTS = "tests/test_generate.py"

# B26 reuses this edit: the same bypass, then the tests that caught it weakened.
_GATE_BYPASS = Edit(
    _GEN,
    "    for cid in _cited_ids(dovidka):\n"
    "        if cid in by_id:\n"
    "            resolved[cid] = by_id[cid]\n"
    "        elif cid not in invalid:\n"
    "            invalid.append(cid)\n",
    "    for cid in _cited_ids(dovidka):\n"
    "        resolved[cid] = by_id.get(cid, cid)\n",
)


def _skip(test: str) -> Edit:
    """Mark one test in test_generate.py as skipped, with the excuse an agent would write."""
    line = f"    def {test}(self):"
    return Edit(_GEN_TESTS, line,
                f'    @unittest.skip("superseded: the resolver now keeps unknown IDs")\n{line}')


BUGS: tuple[Bug, ...] = (
    Bug("B00", "canary", "Import-time crash in the generation module",
        "Not a realistic bug: it proves that the runner applies edits and that the gates see them.",
        (Edit(_GEN, "MAX_RETRIES = 2 ", 'raise RuntimeError("seeded canary")\nMAX_RETRIES = 2 '),),
        canary=True),

    # citation gate: the model picks an ID, code arbitrates
    Bug("B01", "citation gate", "The gate accepts citation IDs outside the candidate set",
        "Asked to stop answers failing on an unknown ID, the agent keeps every cited ID and falls "
        "back to the raw ID as the citation text.",
        (_GATE_BYPASS,)),
    Bug("B02", "citation gate", "One regeneration fewer before the honest abstain",
        "Reads max_retries as the total number of calls and corrects the loop bound.",
        (Edit(_GEN, "    for _attempt in range(max_retries + 1):",
              "    for _attempt in range(max_retries):"),)),
    Bug("B03", "citation gate", "An answer without citations passes when it has a conclusion",
        "Decides that a plain-language conclusion is useful even without citations and only "
        "rejects answers that have neither.",
        (Edit(_GEN, "        elif not resolved:",
              '        elif not resolved and not dovidka.get("vysnovok"):'),)),

    # context budget: whole candidates are dropped, text is never truncated, one always survives
    Bug("B04", "context budget", "The budget can drop every candidate",
        "Simplifies the budget loop; the guarantee to keep at least one candidate goes with the "
        "condition that looked redundant.",
        (Edit(_GEN, "        if out and used + nt > max_tokens:",
              "        if used + nt > max_tokens:"),)),
    Bug("B05", "context budget", "A candidate that fits the budget exactly is dropped",
        "Tightens the budget check to strictly below the limit.",
        (Edit(_GEN, "        if out and used + nt > max_tokens:",
              "        if out and used + nt >= max_tokens:"),)),

    # rendering of the answer
    Bug("B06", "rendering", "Citation chips are rendered without HTML escaping",
        "Removes what looks like double escaping around the citation chip.",
        (Edit(_GEN, '<span class="cite-chip">{e(resolved.get(cid, cid))}</span>',
              '<span class="cite-chip">{resolved.get(cid, cid)}</span>'),)),
    Bug("B07", "rendering", "Internal candidate IDs reach the reader's text",
        "Replaces the cleaning helper with plain escaping; IDs such as C3 stay in the prose.",
        (Edit(_GEN, "_html.escape(_clean(text))", '_html.escape(text or "")'),)),
    Bug("B08", "rendering", "An abstain shows the model's own prose",
        "Shows the model's explanation on an abstain when it has one, instead of the fixed copy.",
        (Edit(_GEN, '    if result.get("abstained"):\n        # FIXED copy',
              '    if result.get("abstained") and not d.get("vysnovok"):\n        # FIXED copy'),)),

    # retrieval
    Bug("B09", "retrieval", "An edition whose last day in force is today is filtered out",
        "Rewrites the in-force check with a strict comparison.",
        (Edit(_RET, "{p}in_force_to >= {aod}", "{p}in_force_to > {aod}"),)),
    Bug("B10", "retrieval", "RRF fusion ignores the calibrated channel weights",
        "Calls the weighting premature and gives every channel the same weight.",
        (Edit(_RET, "        w = weights.get(ch, 1.0)", "        w = 1.0"),)),
    Bug("B11", "retrieval", "A failed retrieval channel disappears without a degradation flag",
        "Treats a failed channel as noise; the fused result looks whole although a channel is lost.",
        (Edit(_RET, "        degraded.append(name)\n", ""),)),
    Bug("B12", "retrieval", "Code abbreviations match case-insensitively",
        "Makes the abbreviation match case-insensitive for robustness; the word «кас» (a cash "
        "desk) now routes a question to the Code of Administrative Procedure.",
        (Edit(_RET, r'if re.search(rf"(?<!\w){re.escape(abbr)}(?!\w)", query):',
              r'if re.search(rf"(?<!\w){re.escape(abbr)}(?!\w)", query, re.IGNORECASE):'),)),
    Bug("B13", "retrieval", "The reranker fallback is not flagged as degraded",
        "Removes the degradation flag in the reranker fallback because the RRF order is good enough.",
        (Edit(_RET, '            meta["degraded"] = meta.get("degraded", []) + ["reranker"]\n', ""),)),
    Bug("B14", "retrieval", "The Ukrainian apostrophe U+02BC is not normalised",
        "Normalises apostrophe variants but forgets the modifier letter apostrophe Ukrainian uses.",
        (Edit(_RET, "for ap in \"’`´ʼ\":", "for ap in \"’`´\":"),)),
    Bug("B15", "retrieval", "«стаття 210-1» is parsed as article 210",
        "Simplifies the article-number pattern to digits only.",
        (Edit(_RET, r'_ART_RE = re.compile(r"\b(?:статт\w*|ст)\.?\s*(\d+(?:-\d+)?)", re.IGNORECASE)',
              r'_ART_RE = re.compile(r"\b(?:статт\w*|ст)\.?\s*(\d+)", re.IGNORECASE)'),)),

    # data governance: user data must never reach the external model
    Bug("B16", "data governance", "The user-data tripwire no longer scans dictionary keys",
        "Stops scanning keys because keys are never user data.",
        (Edit(_LLM, "out.extend(_walk_strings(k))", "pass"),)),
    Bug("B17", "data governance", "The tripwire lets through values it cannot inspect",
        "Skips unknown value types instead of refusing the whole message.",
        (Edit(_LLM,
              "    raise ValueError(\n"
              "        f\"DeepSeek: uninspectable value of type {type(obj).__name__} in message — \"\n"
              "        \"refusing (cannot verify it is PII-free).\")\n",
              "    return []\n"),)),

    # exit codes: cron and orchestrators must see failures
    Bug("B18", "exit codes", "The worst of several exit codes is taken as the numeric maximum",
        "Replaces the severity table with max(); STALE (3) now outranks FAIL (1).",
        (Edit(_EXIT, "    return max(codes, key=lambda c: _SEVERITY.get(c, 3), default=OK)",
              "    return max(codes, default=OK)"),)),
    Bug("B19", "exit codes", "A run that collected less than expected exits 0",
        "Drops the undercount condition as a duplicate of the error count.",
        (Edit(_EXIT, "    return FAIL if (errors or undercount) else OK",
              "    return FAIL if errors else OK"),)),
    Bug("B20", "exit codes", "The snapshot run exits 0 on network errors",
        "Treats a connection reset as transient: the anti-pattern exitcodes.py was written against.",
        (Edit(_KSU, "    if errors or bad_char:", "    if bad_char:"),)),

    # API seam
    Bug("B21", "api", "A 500 response carries the exception text",
        "Adds the exception message to the error body to make debugging easier.",
        (Edit(_API, "        except Exception:", "        except Exception as exc:"),
         Edit(_API, '"Внутрішня помилка сервера.")', 'f"Внутрішня помилка сервера: {exc}")'))),
    Bug("B22", "api", "The dev server listens on every network interface",
        "Binds to 0.0.0.0 to reach the dev server from another machine.",
        (Edit(_API, 'host="127.0.0.1"', 'host="0.0.0.0"'),)),

    # evaluation: the measurement itself
    Bug("B23", "evaluation", "Gold matching by string prefix: ст.21 also matches ст.210",
        "Simplifies the article match to a prefix test.",
        (Edit(_RETEVAL, 'h["unit_path"] == art or h["unit_path"].startswith(art + "/")',
              'h["unit_path"].startswith(art)'),)),
    Bug("B24", "evaluation", "An abstain that still cites something is scored as an answer",
        "Keeps the citations of an abstained answer in the score so they are not lost; recall "
        "is inflated.",
        (Edit(_HARNESS, '    if mf["abstain"]:', '    if mf["abstain"] and not mf["cited"]:'),)),
    Bug("B25", "evaluation", "The harness gate passes despite hallucinated citations",
        "Removes the hallucination condition because the stub cannot hallucinate anyway.",
        (Edit(_HARNESS, '        red = bool(a["hallucination"]) or bool(gr["mechanical_red"])',
              '        red = bool(gr["mechanical_red"])'),)),

    # test integrity: the change and the tests that would have caught it, in one diff
    Bug("B26", "test integrity", "B01, with the five tests that caught it marked as skipped",
        "Faced with five red tests after the B01 change, the agent skips them as superseded by "
        "the new resolver, and the suite is green again.",
        (_GATE_BYPASS,
         _skip("test_in_set_resolves_out_of_set_is_invalid"),
         _skip("test_retry_appends_assistant_tool_call_turn"),
         _skip("test_out_of_set_retries_then_abstains"),
         _skip("test_recovers_on_retry"),
         _skip("test_adversarial_injection_rejected"))),
)
