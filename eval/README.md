# eval — the evaluation harness

The contract of this directory in one rule: **the evaluation never grades itself.** The reference
questions and their gold citations are written outside the pipeline under test, the harness only
scores mechanical facts (which act and article were actually cited, and whether the answer
abstained), and every check that can pass silently is written so that it fails loudly instead.

Nothing here needs a database, a GPU or an API key unless it is explicitly a live run.

## Files

### Code

| File | What it does |
|---|---|
| `schema.py` | Pydantic records: `EvalQuestion` (a gold record), `FaqItem` (a raw harvested Q&A), `RunResult` (one runner output row). |
| `harvest/army_qa.py` | Parses the public `army.gov.ua/qa` FAQ into `data/questions_raw.jsonl`, then drafts a topic selection into `data/questions_v0.jsonl` with empty gold. |
| `runner.py` | The oldest leg: question → LLM answer with no retrieval, plus a trace per call. Kept as the provenance of the trace format, not as a quality measurement. |
| `retrieval_eval.py` | Retrieval metrics per question class and per pipeline layer: recall@k, precision@1, MRR@k for `dense`, `hybrid` (RRF) and `rerank`. Owns `_load_gold`, the single fail-loud gold validator that everything else reuses. |
| `retrieval_baseline.py` | Freezes a retrieval baseline (top-k per gold question) and later re-probes it, so corpus growth cannot silently push a gold norm out of top-k. |
| `harness.py` | The generation harness and gate: taxonomy, `sufficient@k`, the golden regression corpus, the two-pass replay-noise measurement, run persistence. |

### Data

| File | Rows | What it is |
|---|---|---|
| `data/retrieval_gold_v0.jsonl` | 29 | The reference set. `{id, class, question, gold_citations, as_of_date, note}`. |
| `data/smoke_retrieval.jsonl` | 5 | A smoke set in the older field shape `{id, question, expected_act, expected_article, note}`; both shapes load through the same validator. |
| `data/questions_raw.jsonl` | 193 | Every Q&A harvested from the public FAQ, verbatim (`FaqItem`). |
| `data/questions_v0.jsonl` | 42 | The drafted selection (`EvalQuestion`), each tagged `[CLAIM]` with `gold_citations: []` and `validated: false`. |
| `golden/*.jsonl` | 3 | The golden regression corpus (see below). |
| `baselines/retrieval_2026-07-19_14acts.jsonl` | 1 + 29 | A frozen retrieval baseline: a header row plus one row per question. |
| `results/2026-09-10_retrieval_gold29.txt` | — | The captured stdout of a live retrieval run, kept verbatim as the evidence behind the published numbers. |

## The gold set as it is

`data/retrieval_gold_v0.jsonl` holds **29 questions in three classes**:

- **paraphrase (13)** — the question restates the article in ordinary words and shares no rare term
  with it; this is where a dense retriever should already be at its ceiling.
- **distinctive (10)** — the question carries a term that appears almost nowhere else in the corpus.
- **citation (6)** — a direct lookup, "what does article N of act X say"; the class that fails
  hardest without an exact-lookup route, because a citation string is a poor semantic query.

Each row pins its gold as canonical citations of the form `act_nreg ст.N` — for example
`8073-10 ст.289`. The article level is the unit of truth: `частини` and `пункти` underneath it match
by prefix, so `ст.289/ч.2` counts as a hit for `ст.289`. An `atom_id` or a structural object is
rejected by the validator, and so is a non-canonical act number (`3633-IX` instead of `3633-20`).

These questions were **written by the project's lead agent and cross-checked by five independent
agent reviews, never by the model under evaluation.** They were not written or validated by lawyers,
which is the honest limit of what the numbers mean. The `note` field on each row records why that
article is the gold one, including the distractors that were considered and rejected.

The 29 rows are the only scorable set here. `questions_v0.jsonl` has no gold at all, by design.

## The harvested public FAQ

`harvest/army_qa.py` fetches the public FAQ, saves the raw HTML plus its sha256 next to the parsed
output (so the corpus survives the page migrating), and writes:

- **193 raw Q&A pairs** → `data/questions_raw.jsonl`, verbatim;
- **42 drafted claims** → `data/questions_v0.jsonl`, selected by a keyword heuristic over the
  headline topics and topped up to the floor if the heuristic under-shoots.

Every one of those 42 rows is tagged `[CLAIM]` with empty `gold_citations`, empty `gold_key_points`
and `validated: false`. A harvester may propose a question; it may not author the answer it will
later be graded against. That is why running the harness against `questions_v0.jsonl` — which is its
default `--etalons` — exits 1 with "no scorable reference questions" rather than reporting a score.

## The golden regression corpus

`golden/*.jsonl`, committed to git, is the "a bug becomes a permanent test" mechanism. One case per
line: `{bug_ref, kind, question, note, expect}`.

- **`kind: "mechanical"`** — hard. `expect.cited` lists `(act, article)` pairs that must be cited,
  and `expect.abstain` the abstain flag that must hold. One mismatch turns the gate RED. A mechanical
  case is never auto-rebased onto current behaviour; that is what `bug_ref` is for.
- **`kind: "precision_drift"`** — a measured signal. `expect.must_not_contain` lists phrasings that a
  previous run produced where the cited norm was right but the wording over-generalised or inverted
  it. Reported, not gating, because prose flips between runs even at temperature 0.

`load_golden` is fail-loud in three ways: a missing `bug_ref` is rejected, an unknown `kind` is
rejected, and a case without **teeth** is rejected — a mechanical case with neither `cited` nor
`abstain`, or a drift case with no `must_not_contain`, cannot ever fail and is therefore not a
golden case.

## The frozen baselines

The corpus grows. Growing it perturbs the candidate pool: RRF ranks shift, the cross-encoder
re-orders, and a question answered correctly today can silently lose its gold norm out of top-k on a
topic nobody was touching. "We did not break anything" is worth exactly the measurement taken before
the change, so `retrieval_baseline.py` takes that measurement.

A baseline file is a header row (`kind`, timestamp, gold file, `n`, `k`, and the corpus shape the
snapshot was taken against) followed by one row per question: the gold citations, the rank at which
the gold was found, the retrieval route, whether the reranker ran, and the full top-k. Questions are
stored as a sha1 prefix rather than raw text where identity is all that matters.

`--compare` re-probes live and diffs. Gold **lost** from top-k is the RED signal and exits 1. Gold
**gained** and pure rank churn are reported as information — reordering is expected and is not by
itself a regression. A baseline whose gold row no longer exists in the gold file fails loudly as
stale rather than quietly skipping the question.

It is retrieval-only by design: no generation call, so the run is free, fast and deterministic
enough to serve as a regression instrument. Generation noise (measured: 0.310 set-flip at
temperature 0) would drown the signal.

## Running it

```bash
# Offline: no database, no API key, no LM. These are the two commands the top-level README uses.
uv run python -m eval.harness --backend stub --etalons eval/data/retrieval_gold_v0.jsonl
uv run python -m eval.harness --no-llm      --etalons eval/data/retrieval_gold_v0.jsonl

# Offline gate, including the sabotage leg that proves the gate can actually redden.
uv run python -m eval.harness --mode gate --backend stub         --etalons eval/data/retrieval_gold_v0.jsonl
uv run python -m eval.harness --mode gate --backend stub-abstain --etalons eval/data/retrieval_gold_v0.jsonl

# Offline noise-gate pin: stub-flip flips the cited set on every second pass.
uv run python -m eval.harness --mode noise --backend stub-flip --passes 2 \
    --etalons eval/data/retrieval_gold_v0.jsonl

# Live (needs PostgreSQL + pgvector, LM Studio with BGE-M3, the reranker and an API key).
uv run python -m eval.harness --backend live --mode gate --etalons eval/data/retrieval_gold_v0.jsonl
uv run python -m eval.retrieval_eval --gold eval/data/retrieval_gold_v0.jsonl --mode all --k 10
uv run python -m eval.retrieval_baseline --out     eval/baselines/retrieval_<tag>.jsonl
uv run python -m eval.retrieval_baseline --compare eval/baselines/retrieval_<tag>.jsonl

# Harvest (network) and the no-RAG runner (API key, or --backend stub for neither).
uv run python -m eval.harvest.army_qa --snapshot
uv run python -m eval.runner --backend stub --limit 5
```

Offline runs need no corpus to validate against: `harness.py` derives the set of known act numbers
from the gold file itself, and `--known-acts 8073-10,2232-12` overrides that with an explicit list.
Only `--backend live` opens a database connection, because only the generator reads the corpus.
Every other fail-loud check in the validator — citation shape, article form, field types — runs
identically online and offline.

`--mode`:

- `score` (default) — run every reference question, print overall and per-class metrics, persist the
  run. Exits 1 only if a hallucination was recorded.
- `gate` — the same run plus an explicit `GATE [GREEN|RED]` verdict line.
- `noise` — no scoring: run each question `--passes` times and measure how much the mechanical
  answer flips between passes.

## Exit codes

| Code | `harness.py` | `retrieval_eval.py` | `retrieval_baseline.py` | `runner.py` |
|---|---|---|---|---|
| 0 | green | run completed | baseline captured, or no gold lost | run passed |
| 1 | RED: a hallucination, a mechanical golden mismatch, a noise breach, or no scorable gold in the file | no scorable gold, or LM Studio unreachable | gold lost from top-k, or a stale baseline | empty input, no successful results, or an error rate above 50% |
| 2 | a gold or golden format error, or `--backend stub-flip` used outside `--mode noise` | a gold format error | — | backend SKIP: no local chat model is served |

A format error is deliberately a different code from a RED result: a broken input file is not the
same event as a pipeline regression, and the two must not be confused by a CI job.

## What a run is graded on

`mechanical_fields` reduces a generated answer to the fields that are stable enough to diff: the set
of `(act, article-stem)` pairs the model actually cited, the abstain flag, and `outside_set` — any
resolved candidate ID that was not in the candidate set handed to the model. Prose is never diffed.

`classify` turns that into the taxonomy: **correct** (a gold citation is cited), **null** (a gold
citation is missed and the answer did not abstain), **wrong_pick_candidates** (a cited norm that
backs no gold item), **hallucination** (`outside_set` is non-empty — structurally 0, because the
citation gate guarantees it) and **precision_drift_signal** (a gold norm is cited, but the prose
names article numbers outside the resolved set). An abstained answer delivers no citations to the
reader, so it is scored on its own axis and never as if it had answered.

`sufficient_at_k` asks a separate question: was every gold article present in the retrieved
candidates at all? Gold missing from the candidate set is a retrieval miss, not a generation error —
it is the ceiling above which the generation score cannot rise, and it makes a `null` attributable.

The replay-noise gate is two-level. A **gold flip** — the gold article's citation presence differing
between passes — is a hard incident at any count above 0. A **set flip** — the full mechanical key
differing — is thresholded, because the extra, non-gold part of the cited set is genuinely noisy.
`NOISE_FLIP_THRESHOLD = 0.45` is that threshold: it comes from a live 29 × 2 re-measurement on
2026-07-18 that recorded a set-flip rate of 0.310 with 0 gold flips, times a margin of roughly 1.45.
The order matters — the noise floor was measured first and the threshold set above it, because a
threshold chosen before the measurement is a guess.

## Where runs are written

Working runs are data, not source, and they go to `$DATA_DIR/eval/t13/`, which defaults to
`<repo>/data/eval/t13/` and is **gitignored**. Nothing in a run is written anywhere else in the tree.

- `<run_id>.jsonl` — a header row (run id, overall metrics, per-class metrics and the golden verdict)
  followed by one row per reference question: taxonomy, sufficiency, lint flags, the answer prose,
  and the pinned candidate set (candidate IDs, resolved IDs, request IDs).
- `noise_<run_id>.jsonl` — the same shape for a noise measurement: per-pass cited sets, abstain flags
  and request IDs.

`run_id` is `%Y-%m-%dT%H%M%S` in UTC plus the backend name, for example
`2026-07-18T170800_live`. It is unique down to the second on purpose: an earlier day-granular stamp
let a re-run silently overwrite the previous file and destroy the replay history.

Pinning the candidate set is what makes a replay meaningful — the second pass must be diffed against
the same retrieved candidates, not against a fresh retrieval. Persisting the golden verdict and the
answer prose in the artifact is the same idea applied to review: a flagged phrase has to be readable
later from the file, not only from the terminal of whoever ran it.

The harness is only ever pointed at reference questions, which are public or synthetic and contain
no personal data. `write_run` persists answer prose, so it must not be reused for runs over real
user questions.
