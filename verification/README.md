# Verification

This directory answers one question about the repository: **how much of what can go wrong would CI
actually stop?** It holds the gates CI runs and a benchmark that measures them by planting
realistic bugs, one at a time.

## The gates

| Gate | What a pass proves | CI | pre-commit | Benchmark |
|---|---|---|---|---|
| `unit-tests` | the 336 offline tests pass (model, embeddings and reranker mocked) | every push | | yes |
| `test-ratchet` | every recorded test still exists and every skip is on the allowed list | every push | | yes |
| `lint` | ruff finds nothing under the rule set in `pyproject.toml` (E, F, W and S104) | every push | staged files | yes |
| `eval-no-llm` | the reference questions and the golden corpus validate: format, teeth, `bug_ref` | every push | | yes |
| `eval-stub-gate` | the harness gate is GREEN on the oracle stub: no hallucination, no golden case RED | every push | | yes |
| secret scan | no secret in any commit (gitleaks 8.30.1, checksum-verified, full history) | every push | staged changes | |
| dependency audit | no known vulnerability in the packages pinned by `uv.lock` (pip-audit) | every push, weekly | | |

The first five are defined once, in `gates.py`; CI calls them one by one and the benchmark runs all
of them, so the benchmark measures exactly what CI enforces.

The pre-commit gitleaks hook only sees staged changes (`pre-commit run --all-files` stages
nothing), which is why CI scans the history itself. The scan has one documented exception in
`.gitleaksignore`: the sha256 pin of the open BGE-M3 tokenizer in `pipelines/rada/chunk.py`, which
the generic-api-key rule reads as a key. It is ignored by the fingerprint of that single finding, so
any new secret-like string still stops CI.

```bash
uv run python -m verification.gates                  # every gate
uv run python -m verification.gates --only lint      # one gate
```

### The test ratchet

A coding agent can turn a red suite green by deleting or skipping the tests that fail; bug `B26`
below does exactly that. `test_ratchet.py` records every test id, and the allowed skips with their
reasons, in `test_inventory.json`. A recorded test that disappears, or a skip that is not on the
list, fails the gate. It tracks ids rather than counts for two reasons: a deleted test replaced by a
trivial one keeps the count, and skips can differ by platform. The cross-process politeness lock used to be
Windows-only (`msvcrt`), so its seven tests skipped on Linux CI; the lock is now portable, and the
only allowed skip is the optional reranker extra.

Tests added, or a skip made on purpose: `uv run python -m verification.test_ratchet --update` in the
same commit, where a reviewer sees the inventory change.

## The agent layer

The gates stop what a check can express. The rest is left to review, and here review is done by
agents under rules they cannot skip:

- `AGENTS.md` is the source of truth for any coding agent: the commands, the seven invariants of the
  system, the boundaries (never delete, skip or weaken a test; never touch the catalogues, the
  reports or CI as a side effect) and the definition of done, with the evidence marks [LIVE],
  [CODE] and [CLAIM]. `CLAUDE.md` imports it.
- `/review` (`.claude/skills/review/`) runs the gates, gives the diff to the `change-reviewer`
  subagent, which checks it against the invariants and has to prove every finding, and gives every
  serious finding to the `finding-skeptic` subagent, whose job is to refute it. Only confirmed
  findings reach the report in `verification/reviews/`.
- A Stop hook (`.claude/hooks/gates_before_stop.py`) does not let an agent that changed Python files
  finish while a gate is red, and tells it which gate.
- `.claude/settings.json` makes editing the test inventory, the catalogues, the reports, the gate
  list or CI, and pushing, ask a person first; reading `.env` is denied.

## The seeded-bug benchmark

`seeded_bugs/catalogue.py` lists 26 defects of the kind a coding agent introduces while fixing or
simplifying code: a bypassed check, an off-by-one, a flipped comparison, a swallowed degradation
flag, a leaked internal identifier, a test skipped until the suite is green. Each bug carries the
story of how it plausibly happens and its exact edits.

`seeded_bugs/run.py` copies the working tree to a temporary directory and runs every gate on the
untouched copy first; a red baseline stops the run. Then, for each bug, it takes a fresh copy,
applies the edits and runs every gate again. A bug counts as caught when at least one gate fails.

Rules that keep the number honest:

- **Exact edits.** Every edit is a find → replace that must match the current code exactly once.
  When the code moves on, the runner stops with an error instead of measuring a bug that no longer
  exists.
- **A canary.** Every catalogue has one bug that crashes a module at import. If the canary is not
  caught, the runner is broken and nothing is reported.
- **No tuning.** A catalogue is written before its first measured run, and a miss stays in it as a
  documented gap. The one bug derived from a measurement is `B26`: it plants `B01` and skips exactly
  the five tests that caught `B01` in a probe run.
- **A held-out catalogue.** Once tests are written against a catalogue's misses, that catalogue
  becomes a training set: measuring it again shows that the fixes work, not that the gates
  generalise. `seeded_bugs/catalogue_heldout.py` was written after the fixes by an agent that had
  not seen `tests/` or the first catalogue; its number is the one that says how the gates do on bugs
  nobody prepared for.
- **Provenance.** Every report records the git revision and the state of the tree when the snapshot
  was taken, a sha256 digest of the measured tree and the sha256 of the catalogue. Reports are
  never overwritten; a second report on the same day needs its own `--label`.
- **Isolation.** The gates run with API keys and database credentials removed from the environment
  and with `DATA_DIR` in the temporary directory.

```bash
uv run python -m verification.seeded_bugs.run                  # full run, writes the report
uv run python -m verification.seeded_bugs.run --only B06,B25   # a subset, prints only
uv run python -m verification.seeded_bugs.run \
    --catalogue verification/seeded_bugs/catalogue_heldout.py --label heldout
```

## Measurements

### First measurement: 13 of 26

Report: [`reports/seeded-bugs-2026-09-11.md`](reports/seeded-bugs-2026-09-11.md), measured on git
`23ae162`.

| Area | Planted | Caught |
|---|---|---|
| citation gate | 3 | 3 |
| data governance (user-data tripwire) | 2 | 2 |
| exit codes | 3 | 3 |
| rendering | 3 | 2 |
| api | 2 | 1 |
| context budget | 2 | 1 |
| evaluation | 3 | 1 |
| retrieval | 7 | 0 |
| test integrity | 1 | 0 |

The split is the finding. Where the tests were written against incidents (the citation gate, the
user-data tripwire, the exit-code convention) the gates stopped 8 of 8. Retrieval was accepted by
live measurement on the private corpus (recall@k per layer) rather than by tests, and the tests that
need PostgreSQL stayed in the private repository; in this extract the gates stopped 0 of 7
retrieval bugs.

### What the first measurement missed, and what closed each gap

| Gap | Bugs | Why nothing failed | Closed by |
|---|---|---|---|
| Retrieval had no offline tests | B09–B15 | `search()` appeared in the suite only as a mock; `_rrf`, `_run_channel`, `_act_mentions`, `_norm` and `_ART_RE` were never called | `tests/test_retrieval_offline.py`: the scope clause, fusion under the calibrated weights, degradation flags, the reranker fallback, the exact route (article suffixes, abbreviation case, act binding, round-robin) and normalisation |
| A boundary nobody pinned | B05 | the budget test used 4 000-token candidates against a 10 000-token budget, so "fits exactly" never occurred | `test_candidate_that_fits_exactly_is_kept` |
| An escaping test one field short | B06 | markup went into the prose fields, never into the citation string of a chip | `test_escapes_markup_inside_a_citation_chip` |
| A gate branch covered at unit level only | B25 | the CLI test drove only the golden-RED branch of `--mode gate` | a `stub-hallucinate` backend and `test_hallucination_alone_turns_the_gate_red` |
| Configuration outside any test | B22 | nothing calls `main()`, and E/F/W had no security rule | ruff `S104` in the lint gate |
| An evaluation helper untested | B23 | `_gold_rank` ran only inside the live retrieval eval | `tests/test_gold_rank.py` |
| Test integrity | B26 | the bypass and the skips landed in one diff, so every gate stayed green | the test ratchet |

### Re-measured after the fixes: 26 of 26, overfit by construction

Report: [`reports/seeded-bugs-2026-09-11-v1-after-fixes.md`](reports/seeded-bugs-2026-09-11-v1-after-fixes.md),
measured on git `6ce4ca0`.

All thirteen misses are now caught. That shows the fixes work; it does not show that the gates
generalise, because the tests were written knowing which bugs they had to stop. The held-out
measurement answers that question.

### Held-out: 12 of 20

Report: [`reports/seeded-bugs-2026-09-11-heldout.md`](reports/seeded-bugs-2026-09-11-heldout.md),
measured on git `fc5359e`.

Six held-out bugs repeat a defect class of the first catalogue, found independently. The split
below was fixed in the catalogue's commit message, before the measurement.

| Held-out bugs | Planted | Caught |
|---|---|---|
| classes the first catalogue already had (H01, H07, H08, H09, H15, H16) | 6 | 6 |
| new classes | 14 | 6 |
| all | 20 | 12 |

**6 of 14 on new classes is the number that describes the gates on bugs nobody prepared for.** Of
those six, one is caught by a test from the gap round that was not aimed at a planted bug (the
round-robin order of the exact route, H02); the other five by tests that predate this work and were
written against real incidents (the tripwire, the politeness table, the units ledger, the citation
of approved blocks, the dedupe of duplicate paths).

| Area | Planted | Caught |
|---|---|---|
| api | 1 | 1 |
| citation gate | 1 | 0 |
| collection | 3 | 2 |
| context budget | 1 | 0 |
| data governance | 2 | 2 |
| evaluation | 4 | 2 |
| exit codes | 3 | 1 |
| parsing | 1 | 1 |
| rendering | 1 | 1 |
| retrieval | 3 | 2 |

What the gates missed:

| Bug | Why nothing failed | What would close it |
|---|---|---|
| H05: an out-of-set id passes when a valid one is cited beside it | the injection test feeds exactly this answer but checks only that the fabricated id is not resolved, not that the answer was rejected and regenerated | assert the regeneration in that test; this is the citation gate's core invariant |
| H03: reranked candidates ordered worst-first | no test checks the order `search()` returns after a successful rerank | a fake reranker and an ordering test |
| H04: an over-budget candidate skipped instead of ending the list | in every budget test the sizes make `continue` and `break` agree | a large candidate followed by small ones |
| H11: Rada's daily byte cap raised past the published limit | the real `CAP_BYTES` is pinned nowhere; one test uses its own stub value | pin the cap under the published 200 MB a day |
| H17: the replay-noise threshold raised to 0.95 | the noise test drives a flip rate of 1.0, above any threshold, and nothing pins 0.45 | pin the measured threshold |
| H18: a retrieval-baseline regression exits 0 | `eval/retrieval_baseline.py` has no tests | an exit-code test for the regression branch |
| H19: reachability RED reported as a planned skip | the reachability tests do not look at the exit code | pin the RED → FAIL mapping |
| H20: the card fetch exits 0 despite fetch failures | `fetch_cards` has no exit-code test; the suite mentions it in a comment only | the exit-code test the other collectors have |

Five of the eight are exit codes and pinned constants: places where a change looks harmless and a
test has to state the number on purpose.

Closing these eight turns the held-out catalogue into training data too. The next honest number
needs a new held-out catalogue, written after the next round of fixes by an agent that has not seen
the tests.

### Third catalogue (v3): 10 of 20

Report: [`reports/seeded-bugs-2026-09-11-v3.md`](reports/seeded-bugs-2026-09-11-v3.md), measured on
git `32dff05`, after the fixes for the held-out misses. The catalogue was written blind, like the
held-out one, and committed before the run together with the split below.

| v3 bugs | Planted | Caught |
|---|---|---|
| repeats of an earlier catalogue's class (the same mistake in the same mechanism) | 9 | 7 |
| new classes | 11 | 3 |
| all | 20 | 10 |

Two repeats got through, each in the shadow of a caught relative: the citation rule exempting an
answer without theses (V05, a variant of B03) and the units ledger ignoring growth (V19, the other
side of the line H12 changed). The three new classes that were caught fell to tests from the gap
rounds (the fusion order, V02; the budget, V06) and to an existing backstop test (V16).

What the gates missed:

| Bug | Why nothing failed |
|---|---|
| V01: the retrieval channels scope-gate on today, not on the requested `as_of` | the scope test checks the SQL clause; no test follows `as_of` from `search()` into the channels |
| V05: an answer without theses is accepted with no citation | every gate test's answer carries theses; none leaves them empty |
| V07: the user-data tripwire is logged and skipped on the generation path | the tripwire tests call the guard directly and the generation tests mock `call_tool_deepseek`, so nothing runs the guard inside it |
| V08: a provider outage is answered as a 200 abstain | the API's 503 test raises from an injected `generate()`; no test makes the provider call inside `generate()` fail |
| V11: golden cases that raise are skipped and the gate stays green | the golden tests feed wrong answers, never a call that raises |
| V13: an unclosed amendment quote no longer fails the parse run | the detector is tested; the exit code of the run that uses it is not |
| V14: `fetch_texts` skips the polite pause | `fetch_texts` has no test; the politeness tests pin the policy table, not whether a caller uses it |
| V15: the freshness probe compares a new signal with a failed probe's NULL | the query never runs in a test: the one test that touches the previous signal mocks it |
| V18: the amendment-marker pattern turns greedy and deletes the text between two notes | no test has a unit whose text between two notes would be lost; the whole suite passes with the greedy pattern |
| V19: the units ledger no longer flags units injected into a known edition | the ledger tests cover a deletion, a vanished edition and a new edition, not growth inside a known one |

Six of the ten sit next to a check that is tested, on a path that is not: the guard is tested but
not where generation calls it, the detector but not the exit code, the scope clause but not the
argument that reaches it. A unit test pins a function; an agent's change breaks the wiring around
it. These ten are the bug items of the review-layer benchmark in `review_layer/`.

### The review layer on the gates' misses: 10 of 10, no false alarm

Protocol, items, key, every raw output and the grading: [`review_layer/`](review_layer/). The
protocol was committed before any reviewer ran.

The ten v3 bugs the gates missed and nine clean changes were each reviewed twice: by this
repository's `change-reviewer` and by a generic reviewer, the `code-reviewer` agent of
everything-claude-code, on the same model, with the same tools and the same output format.

| Reviewer | Bugs caught | False alarms on clean changes |
|---|---|---|
| change-reviewer alone | 10 of 10 | 0 of 9 |
| change-reviewer + finding-skeptic (the layer as shipped) | 10 of 10 | 0 of 9 |
| generic code-reviewer (ECC) | 10 of 10 | 0 of 9 |

Every serious finding named the planted line and the changed behaviour, and nearly all came with a
run that showed the old and the new behaviour side by side. The skeptic examined all 14 serious
findings of the change-reviewer and confirmed all 14.

What this shows: on single planted defects, a reviewer agent that reads the repository and runs
code closes the gap the gates leave, without raising alarms on clean changes. What it does not
show: a difference between the two reviewers, since both are at the ceiling and the generic one
also read `AGENTS.md` and cited its invariants; or what the skeptic is worth, since there was no
false finding for it to remove. The next measurement needs harder items: larger diffs, several
defects in one change, descriptions that argue for the change, and the generic reviewer without
`AGENTS.md`. Review is also the expensive layer: each review took 3 to 10 minutes of agent time,
where the gates take seconds.

### After the v3 fixes: every catalogue caught in full, all of them training data

Twenty-two offline tests close the ten v3 misses, each pinning the invariant the bug broke: `as_of`
reaches every channel, an answer without theses is regenerated, the tripwire holds at both DeepSeek
entry points, a provider error propagates, a golden call that raises cannot leave the gate green,
the parse run fails on an unclosed quote, every Rada request waits the polite pause, the previous
freshness signal skips a failed probe's NULL, two amendment notes keep the text between them, and
the ledger flags growth. Re-measured on the committed tree, the first catalogue scores 26 of 26, the
held-out one 20 of 20 and v3 20 of 20
([`reports/seeded-bugs-2026-09-11-v3-after-fixes.md`](reports/seeded-bugs-2026-09-11-v3-after-fixes.md)).
All three are training data now; the next honest number needs a fourth catalogue, written blind
after these fixes.

### Fourth catalogue (v4), written blind after the fixes: 17 of 20

Report: [`reports/seeded-bugs-2026-09-11-v4.md`](reports/seeded-bugs-2026-09-11-v4.md), measured on
git `78ac935`. The split below was fixed in the catalogue's commit message, before the run.

| v4 bugs | Planted | Caught |
|---|---|---|
| repeats of a defect class an earlier catalogue already had | 14 | 14 |
| new classes | 6 | 3 |
| all | 20 | 17 |

Fourteen repeats to six new classes is itself a result: after three catalogues a fourth blind author
lands mostly on ground already walked, and the gates now hold all of it, where the first catalogue
held 13 of 26. The number that carries information is 3 of 6 on the classes nobody had planted
before.

| Missed | Why nothing failed |
|---|---|
| W05: candidate dedup groups by article number alone, so the same article number in two acts collapses into one candidate | `dedup_candidates` is tested, but inside one act only: the fixtures vary the unit path and never the act, so a key that ignores the act changes nothing they can see |
| W11: the replay-noise gate no longer turns RED on a gold-citation flip by itself | the gold-flip branch is counted, never gated: the unit test asserts the flip count, and the end-to-end noise test drives the rate branch — its own comment says the gold branch is covered at unit level |
| W16: an article's text no longer contains its own heading | the parser tests pin section texts and what must not be pulled into them; none asserts that an article's heading is part of its text |

All three have the shape of the v3 misses: the function is tested, the property beside it is not.

## What these numbers are not

- The seeded-bug numbers measure the deterministic gates only. The review layer is measured
  separately (`review_layer/`), on the gates' misses and on clean changes, because a reviewer shown
  only planted bugs would be rewarded for flagging everything.
- They are not a quality score for the code. They are the share of these planted defects that CI
  would stop.
- The catalogues are small and were written by coding agents, the same kind of author as the code,
  so they may lean towards bugs an agent can imagine. They are published so that they can be
  challenged.
- Each bug is a single planted change; real defects interact.
- The secret scan and the dependency audit run in CI but are outside the benchmark: there is no
  code bug to plant for them.
