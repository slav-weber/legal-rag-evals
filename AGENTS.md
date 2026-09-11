# AGENTS.md

Instructions for coding agents, and for people, working in this repository. `CLAUDE.md` imports
this file; other agents read it directly.

## What this repository is

A curated, verifiable extract of a Ukrainian statute RAG: the retrieval pipeline, the structural
citation gate and the evaluation harness. Python 3.12 with uv. User-facing text and the corpus are
Ukrainian by design; code, comments and documentation are English. Start with `README.md` and
`docs/ARCHITECTURE.md`.

## Commands

```bash
uv sync                                          # the locked environment
uv run python -m verification.gates              # every deterministic gate, exactly what CI runs
uv run python -m unittest discover -s tests -q   # the test suite alone
```

Nothing here needs a database, a GPU or an API key. The live path is described in the README and is
not part of the checks.

## Invariants: never propose a change that breaks one

1. **The model picks an ID, code arbitrates.** The generator may cite only candidate IDs from the
   closed per-request set, and code resolves every cited ID. An ID outside the set rejects the whole
   answer (regenerate at most twice, then an honest abstain), even when valid IDs are cited next to
   it. An answer without citations is not an answer. (`pipelines/rag/generate.py`)
2. **User data never reaches the external model.** The tripwire in `ml/llm_client.py` fails closed:
   anything it cannot inspect is refused, and keys and nested values are scanned.
3. **Only editions in force on `as_of` are served**, filtered before scoring, with both bounds
   inclusive. (`scope_clause` in `pipelines/rag/retrieval.py`)
4. **Degradation is loud.** A lost retrieval channel or reranker is flagged in `meta["degraded"]` and
   never passed off as a whole result; the reranked order is best-first.
5. **Exit codes tell the truth.** One convention, in `pipelines/exitcodes.py`: errors or an undercount
   are FAIL, a planned defer is SKIP, and a run in which something failed never exits 0.
6. **Politeness and budgets are enforced, not advisory.** Per-host pauses and daily caps in
   `pipelines/politeness.py` and `pipelines/rada/budget.py` stay at or under the sources' published
   limits.
7. **Measurements are not tuned to results.** Gold files, golden cases and thresholds in `eval/`, and
   the seeded-bug catalogues, change only on purpose, with the reason in the commit.

## Boundaries: what an agent must not do here

- Do not delete, skip or weaken a test to make the suite green. The test ratchet
  (`verification/test_ratchet.py`) fails on it, and changing `verification/test_inventory.json`
  needs a human decision in the same commit.
- Do not edit `verification/seeded_bugs/` or `verification/reports/` unless that is the task.
- Do not add network calls, API keys or database access to tests.
- Do not read or write `.env`, and never commit a secret.
- Do not change CI (`.github/workflows/`) or the gate list (`verification/gates.py`) as a side
  effect of another task.

## Definition of done

A change is done when `uv run python -m verification.gates` is green **and** the claim of what it
does is backed by evidence: a test that fails without the change, a gate's output, or a measured
run. In reports, mark each claim **[LIVE]** (observed at runtime), **[CODE]** (read in the source)
or **[CLAIM]** (asserted, not backed), and write "verified" only next to a link to a committed
artifact.

## Review

`/review` (Claude Code, `.claude/skills/review/`) runs the adversarial review of a change: a
reviewer reads the diff against the invariants above, an independent skeptic tries to refute each
finding, and the confirmed findings are written to `verification/reviews/`.
