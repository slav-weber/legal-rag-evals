# legal-rag-evals

Retrieval pipeline, structural citation gate and evaluation harness of a Ukrainian statute RAG
(retrieval-augmented generation), published as a curated, verifiable extract of a private system.

The system answers legal questions in Ukrainian with citations to the exact article of the exact
edition of a Ukrainian act. Its design rule is **"the model picks an ID, code arbitrates"**: the
language model may only cite candidate IDs handed to it in the prompt, a deterministic resolver
turns each ID into the citation string stored in the database, and an ID outside the candidate set is
rejected, regenerated at most twice and then turned into an honest abstain. A hallucinated citation is
therefore structurally impossible rather than discouraged by prompt wording.

Everything user-facing is in Ukrainian by design (the product was built for Ukraine). Documentation,
comments and log messages are in English; a few example questions below carry an English gloss.

## What this repository shows

| Area | What is here | Where |
|---|---|---|
| Corpus pipeline | Rada edition text → structural units (article, part, point, annex) with stable `unit_path`, edition dates and amendment provenance; units → citable chunks with an `atom_id = (act, unit_path, edition_date)`; the 8192-token gate is decided by the real BGE-M3 tokenizer, pinned by revision and sha256 | `pipelines/rada/parse_structure.py`, `pipelines/rada/chunk.py` |
| Retrieval | Temporal scope gate first (only editions in force on `as_of`), then dense (pgvector, BGE-M3), full-text and Ukrainian-lemma channels fused by reciprocal-rank fusion (weights 2.0 / 0.5 / 0.5, k = 60), an exact-lookup route for "article N of act X" questions, and a cross-encoder reranker (bge-reranker-v2-m3, weights pinned by sha256) with an honest degradation ladder when a layer is unavailable | `pipelines/rag/retrieval.py`, `ml/embed_index.py`, `ml/lemma_index.py`, `ml/reranker.py` |
| Generation | Closed per-request candidate dictionary (C1..Ck), strict function-calling output, structural citation gate, regenerate-then-abstain, a 10 000-token context budget that drops whole candidates rather than truncating text, act-aware citation rendering, a flag for internal vocabulary leaking into user prose | `pipelines/rag/generate.py` |
| Data governance | A user-data sentinel: anything wrapped as user data can never be sent to the external model (tripwire in the client), open data flows freely | `ml/llm_client.py` |
| API seam | One endpoint, `POST /api/generate`, bound to 127.0.0.1, uniform error bodies, a 120 s worst-path timeout, reranker pin verified at startup | `api/main.py` |
| Evaluation | Retrieval metrics per question class (recall@k, precision@1, MRR@k) per layer; generation taxonomy (correct / null / wrong pick / hallucination / precision drift), `sufficient@k`, a golden regression corpus, a two-pass replay-noise gate at temperature 0, frozen retrieval baselines with a regression detector | `eval/` |
| Collection discipline | Per-host politeness and daily budgets under a cross-process lock, Europe/Kyiv day boundaries, one exit-code convention, freshness probes of the sources, a units ledger that catches partial deletions | `pipelines/politeness.py`, `pipelines/freshness/`, `pipelines/exitcodes.py`, `pipelines/units_ledger.py` |

Not included: the corpus itself (statute texts are fetched from open data, see `DATA-LICENSE.md`), the
court-decision perimeter of the private system, internal reports and the working journal.

## Verify it in five minutes

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/). No database, GPU or API key is
needed for the test suite.

```bash
uv sync
uv run python -m unittest discover -s tests -q
uv run python -m eval.harness --backend stub --etalons eval/data/retrieval_gold_v0.jsonl
uv run python -m eval.harness --no-llm --etalons eval/data/retrieval_gold_v0.jsonl
```

The suite runs offline: the language model, the embedding server and the reranker are mocked, and
the tests that need a live PostgreSQL database were left in the private repository. `--backend stub`
exercises the whole harness (loading, validation, scoring, taxonomy, golden corpus, run files) on a
mocked generator; `--no-llm` is the deterministic gate that validates the reference questions and the
golden corpus without calling anything.

## Verification

[![verify](https://github.com/slav-weber/legal-rag-evals/actions/workflows/verify.yml/badge.svg)](https://github.com/slav-weber/legal-rag-evals/actions/workflows/verify.yml)

Every push runs the same gates in CI: the test suite and a ratchet that stops tests from being
deleted or skipped, ruff, the two offline harness gates, a secret scan over the full git history
and an audit of the locked dependencies (`.github/workflows/verify.yml`, `verification/gates.py`).
Coding agents working here follow `AGENTS.md`: the system's invariants, what an agent must not do,
and what "done" means. In Claude Code, `/review` adds an adversarial reviewer and a skeptic, and a
Stop hook refuses "done" while a gate is red.

How much do those gates actually catch? `verification/seeded_bugs/` plants realistic defects one
at a time (a bypassed citation gate, an off-by-one, a flipped comparison, a swallowed degradation
flag, tests skipped until the suite is green) and records which gate stops each one.

- **First measurement: 13 of 26.** 8 of 8 in the citation gate, the user-data tripwire and the exit
  codes; 0 of 7 in retrieval, which this extract had tested only through live evaluation.
- The gaps were closed with offline retrieval tests, boundary and escaping tests, an end-to-end gate
  test, ruff S104 and the test ratchet. The same catalogue then scores 26 of 26, which shows only
  that the fixes work.
- **Held-out catalogue, written afterwards by an agent that never saw the tests: 12 of 20, and 6 of
  14 on defect classes the first catalogue did not have.** The most instructive miss: a change that
  lets the citation gate accept an answer citing a real candidate next to a fabricated one would
  pass the tests.
- **Third catalogue, written blind after the held-out misses were closed: 10 of 20;** 7 of 9 on
  repeated defect classes, 3 of 11 on new ones. Six of the ten misses sit next to a tested check,
  on a path no test runs: the user-data guard is tested, but not where generation calls it.
- **Agent review of the ten v3 bugs the gates missed, plus nine clean changes: 10 of 10 caught,
  no serious false alarm.** This repository's reviewer with its skeptic (`/review`) and a generic
  reviewer (ECC's code-reviewer) both found every bug, so at this size the result speaks for agent
  review, not for one prompt over the other. Protocol, raw outputs and grading:
  `verification/review_layer/`.
- Tests for the ten v3 misses followed; all three catalogues are now caught in full (26, 20 and 20),
  which makes them training data. A fourth catalogue, written blind after these fixes, is the next
  honest number.

Reports: `verification/reports/`; the method and every miss with its reason: `verification/README.md`.

```bash
uv run python -m verification.gates
uv run python -m verification.seeded_bugs.run
```

## Results

Measured on the private corpus (11 acts, 4 706 citable chunks, 4 680 embeddings) with the 29
reference questions in `eval/data/retrieval_gold_v0.jsonl`. Full tables, ablations and the list of
what the numbers do not show: `docs/RESULTS.md`.

Retrieval, k = 10, run on 2026-09-10 (this code, private corpus, see `eval/results/`):

| Question class (n) | Dense only | Hybrid (RRF) | Hybrid + exact lookup + reranker |
|---|---|---|---|
| paraphrase (13) | recall 1.000 · p@1 0.923 · MRR 0.962 | 1.000 · 0.923 · 0.962 | 1.000 · 0.923 · 0.938 |
| distinctive (10) | 1.000 · 1.000 · 1.000 | 1.000 · 1.000 · 1.000 | 1.000 · 0.900 · 0.950 |
| citation (6) | 0.167 · 0.000 · 0.019 | 0.167 · 0.000 · 0.019 | **1.000 · 1.000 · 1.000** |

Generation, acceptance run of 2026-07-19 (private pipeline, external model, 29 questions):
29/29 correct, 0 hallucinated citations, `sufficient@10` 29/29, 5 precision-drift signals, 0 abstains.
Two-pass replay at temperature 0: set-flip rate 0.310, gold-citation flips 0.

The citation class is the instructive one: a question such as *«Що передбачає стаття 210 Кодексу
України про адміністративні правопорушення?»* (What does Article 210 of the Code of Administrative
Offences provide?) fails structurally in dense and hybrid retrieval, because no chunk contains the
literal *«стаття 210»*; the exact-lookup route closes the class from 0.167 to 1.000.

## Example questions

| Ukrainian (as evaluated) | English gloss | Class |
|---|---|---|
| Протягом якого часу можна подати позов до адміністративного суду? | Within what period can a claim be filed with an administrative court? | paraphrase |
| Що таке Єдиний реєстр боржників і чи є його відомості відкритими? | What is the Unified Register of Debtors and is its data public? | distinctive |
| Про що йдеться у статті 289 КУпАП? | What is Article 289 of the Code of Administrative Offences about? | citation |

## Architecture

`docs/ARCHITECTURE.md` describes the layers, the invariants and the reasons behind the choices
(why a closed candidate dictionary, why the scope gate runs before scoring, why a hand-rolled hybrid
retriever rather than a framework, why the tokenizer is pinned).

## Running the live path

The live path needs PostgreSQL with pgvector (`docker compose up -d db`), an OpenAI-compatible
embedding server with BGE-M3 (LM Studio on `localhost:1234` in development), the optional reranker
extra (`uv sync --extra rerank`, CUDA) and an API key for the generation model. Copy `.env.example`
to `.env`, run the migrations in `pipelines/migrations/`, fetch and parse acts with the
`pipelines/rada` tools, build chunks, then `uv run python -m eval.retrieval_eval --mode all`.
This repository ships no corpus, so the live path is documented, not required.

## How this was built

Designed, specified and accepted by Slava Weber; the implementation was typed by coding agents
(Claude Code) working from specifications, acceptance criteria and reference questions written for
each task, then accepted against tests, measured runs and the gates described under Verification. In the private repository 185 of 186 commits carry
the agent's `Co-Authored-By` trailer. The reference questions were written by the project's lead
agent and cross-checked by five independent agent reviews; they were never written by the model
under evaluation.

This public extract was assembled on 10–11 September 2026 by a coding agent from a written plan:
files were selected, Russian and mixed-language comments were translated into English, internal
process notes were removed, one change was made to the harness so that the stub and no-LLM modes run
without a database, and the optional reranker dependencies were moved to an extra. No metric,
threshold, query or gate logic was changed. The commit history of the private repository is not
included.

## What this does not show

- Numbers come from 29 reference questions over 11 acts; they are a reproducible measurement of one
  small corpus, not a benchmark claim.
- Generation numbers were measured once, in July 2026, on the private pipeline with an external model;
  the retrieval numbers above were re-measured on 2026-09-10 with this code against the private corpus.
- The court-decision layer of the private system (collection, anonymisation markers, checks) is not
  part of this extract.

## Licence

Code: PolyForm Noncommercial 1.0.0 (`LICENSE.md`). Statute texts referenced by the evaluation data
are Ukrainian open data, see `DATA-LICENSE.md`.
