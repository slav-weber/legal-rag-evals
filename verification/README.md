# Verification

This directory answers one question about the repository: **how much of what can go wrong would CI
actually stop?** It holds the gates CI runs and a benchmark that measures them by planting
realistic bugs, one at a time.

## The gates

| Gate | What a pass proves | CI | pre-commit | Benchmark |
|---|---|---|---|---|
| `unit-tests` | the 280 offline tests pass (model, embeddings and reranker mocked) | every push | | yes |
| `lint` | ruff finds nothing under the rule set in `pyproject.toml` (E, F, W) | every push | staged files | yes |
| `eval-no-llm` | the reference questions and the golden corpus validate: format, teeth, `bug_ref` | every push | | yes |
| `eval-stub-gate` | the harness gate is GREEN on the oracle stub: no hallucination, no golden case RED | every push | | yes |
| secret scan | no secret in any commit (gitleaks 8.30.1, checksum-verified, full history) | every push | staged changes | |
| dependency audit | no known vulnerability in the packages pinned by `uv.lock` (pip-audit) | every push, weekly | | |

The first four are defined once, in `gates.py`; CI calls them one by one and the benchmark runs all
of them, so the benchmark measures exactly what CI enforces. The pre-commit gitleaks hook only sees
staged changes (`pre-commit run --all-files` stages nothing), which is why CI scans the history
itself.

```bash
uv run python -m verification.gates                  # every gate
uv run python -m verification.gates --only lint      # one gate
```

## The seeded-bug benchmark

`seeded_bugs/catalogue.py` lists 26 defects of the kind a coding agent introduces while fixing or
simplifying code: a bypassed check, an off-by-one, a flipped comparison, a swallowed degradation
flag, a leaked internal identifier, a test skipped until the suite is green. Each bug carries the
story of how it plausibly happens and its exact edits.

`seeded_bugs/run.py` copies the working tree to a temporary directory and runs every gate on the
untouched copy first; a red baseline stops the run. Then, for each bug, it takes a fresh copy,
applies the edits and runs every gate again. A bug counts as caught when at least one gate fails.

Rules that keep the number honest:

- **Exact edits.** Every edit is a find → replace that must match the current code exactly once. When
  the code moves on, the runner stops with an error instead of measuring a bug that no longer exists.
- **A canary.** `B00` crashes a module at import. If the canary is not caught, the runner is broken
  and nothing is reported.
- **No tuning.** The catalogue was written before the first measured run. A miss stays in it as a
  documented gap. The one bug derived from a measurement is `B26`: it plants `B01` and skips exactly
  the five tests that caught `B01` in a probe run.
- **Provenance.** The report records the git revision, a sha256 digest of the measured tree and the
  sha256 of the catalogue.
- **Isolation.** The gates run with API keys and database credentials removed from the environment
  and with `DATA_DIR` in the temporary directory.

```bash
uv run python -m verification.seeded_bugs.run                  # full run, writes the report
uv run python -m verification.seeded_bugs.run --only B06,B25   # a subset, prints only
```

## First measurement, 2026-09-11

**13 of 26 planted bugs caught.** Report: [`reports/seeded-bugs-2026-09-11.md`](reports/seeded-bugs-2026-09-11.md).

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
user-data tripwire, the exit-code convention) the gates stop 8 of 8. Retrieval was accepted by live
measurement on the private corpus (recall@k per layer) rather than by tests, and the tests that
need PostgreSQL stayed in the private repository; in this extract the gates stop 0 of 7 retrieval
bugs.

## What the gates missed, and what would close each gap

| Gap | Bugs | Why nothing failed | What closes it |
|---|---|---|---|
| Retrieval has no offline tests | B09–B15 | `search()` appears in the suite only as a mock; `_rrf`, `_run_channel`, `_act_mentions`, `_norm` and `_ART_RE` are never called | offline tests for the pure parts: fusion order under the weights, degradation flags, abbreviation case, apostrophe folding, article suffixes; a pin for the SQL scope clause |
| A boundary nobody pinned | B05 | the budget test uses 4 000-token candidates against a 10 000-token budget, so "fits exactly" never occurs | one boundary test |
| An escaping test one field short | B06 | the test puts markup into the prose fields, never into the citation string of a chip | markup inside a resolved citation |
| A gate branch covered at unit level only | B25 | the taxonomy counts a hallucination, but the CLI test drives only the golden-RED branch of `--mode gate` | a hallucinating stub and an end-to-end test that it turns the gate RED |
| Configuration outside any test | B22 | nothing calls `main()`, and E/F/W has no security rules | ruff `S104`: it flags the planted line and nothing in the current code (checked) |
| An evaluation helper untested | B23 | `_gold_rank` runs only inside the live retrieval eval | a unit test with ст.21 against ст.210 |
| Test integrity | B26 | by construction: the bypass and the skips land in one diff, so every gate stays green | a ratchet on the number of tests and skips, and a reviewer that reads test diffs |

## What this number is not

- It measures the deterministic gates only. The agent-review layer is not in it yet; it will be
  measured against the same catalogue, which is the point of keeping the catalogue fixed.
- It is not a quality score for the code. It is the share of these 26 defects that CI would stop.
- The catalogue is small and was written by a coding agent, the same kind of author as the code, so
  it may lean towards bugs its author can imagine. It is published so that it can be challenged.
- Each bug is a single planted change; real defects interact.
- The secret scan and the dependency audit run in CI but are outside the benchmark: there is no
  code bug to plant for them.
