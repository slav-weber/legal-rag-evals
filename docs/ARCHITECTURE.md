# Architecture

A statute RAG has one hard requirement that a general chatbot does not: every citation must point at
an article that exists, in the edition that was in force on the date the question is about. The
architecture below is organised around making that a property of the code, not of the prompt.

```
open data (data.rada.gov.ua)
   │  fetch cards / texts / links, politeness + daily budget per host
   ▼
editions ──► units (розділ / глава / стаття / частина / пункт / додаток; stable unit_path)
   │            amendment markers {…} pulled out as provenance
   ▼
chunks  = one citable unit of one edition; atom_id = (act_nreg, unit_path, edition_date)
   │      8192-token gate by the real BGE-M3 tokenizer (pinned); oversize → children
   ▼
retrieval: scope gate (in force on as_of) → dense ⊕ FTS ⊕ lemma → RRF → exact-lookup route → rerank
   ▼
generation: candidates C1..Ck → strict function-calling → structural citation gate → abstain
   ▼
API: POST /api/generate on 127.0.0.1 → {answer, citations, degraded, request_id}
```

## 1. Corpus: units and citable chunks

`pipelines/rada/parse_structure.py` splits an edition text into structural units keyed by a stable,
article-number-based `unit_path` (`ст.4`, `ст.13-1`, `ст.4/п.4`, `розд.VI-1`, `дод.5/п.2`). The same
article keeps the same path across editions, so editions diff cleanly. Amendment markers `{…}` are
removed from the clean text and stored as provenance, so a diff shows substantive change, not churn in
change-history notes. The parser handles Roman and Arabic chapter numbers, superscript article numbers
collapsed by the text export (`131` → `ст.13-1`, disambiguated by structural position), resolutions
without articles (points, approved documents and annexes each restart their numbering, so each is its
own scope), and annexes that restart Roman sections.

`pipelines/rada/chunk.py` turns units into chunks. A chunk is one citable unit of one edition, never a
sliding window; that is what makes the citation gate structural, because a citation can only name an
`atom_id` a retrieved chunk actually has. Every unit with its own text is a chunk (an article and each
of its parts), which costs ×1.15 chunks and ×1.72 characters over leaves-only and was measured, not
guessed. A body-bearing container duplicates its children's text, so consumers must be kind-aware.
The 8192-token limit is decided by the real BGE-M3 tokenizer, pinned by revision and sha256; a proxy
was measured (chars per token: min 2.135, median 4.344) and rejected as twice too strict.

## 2. Retrieval

`pipelines/rag/retrieval.py`.

1. **Scope gate first.** Every candidate is filtered by "edition in force on `as_of`" before any
   scoring, in one SQL predicate reused by every channel. A not-yet-in-force or expired edition is
   never served and never costs budget. Correctness is proven by a fixture (an expired and a future row
   must both drop), not by a live run where there is nothing to drop.
2. **Three channels.** Dense (pgvector, BGE-M3 via an OpenAI-compatible embedding server, model
   pinned by reference vectors in `ml/embeddings_reference.json`), PostgreSQL full-text search, and a
   lemma channel built with `pymorphy3` Ukrainian morphology (`ml/lemma_index.py`), because plain FTS
   without stemming misses inflected forms.
3. **Reciprocal-rank fusion** with calibrated weights (dense 2.0, FTS 0.5, lemma 0.5, k = 60, top-N
   50). The calibration was an ablation: equal weights lowered precision@1 on paraphrase questions
   from 0.846 to 0.769; the calibrated weights restored dense parity.
4. **Exact-lookup route.** Questions that name an article number and an act ("стаття 210 …") are
   answered by a regex-and-SQL route, no model involved. This closed the citation class from 0.167 to
   1.000 recall@10: no chunk contains the literal phrase "стаття 210", so no embedding can find it.
5. **Cross-encoder reranker** (`ml/reranker.py`, bge-reranker-v2-m3, weights pinned by sha256 and
   revision, run in-process on the GPU). Unavailable or drifted weights are reported honestly and the
   pipeline degrades down the ladder with a `degraded` flag, rather than silently passing RRF results
   off as reranked.

Why a hand-rolled retriever: the runtime had to be offline-capable, dependency-light and
deterministic under test. The design maps one-to-one onto pgvector plus a reranker, and each layer was
added only after it showed a measurable gain on the reference questions.

## 3. Generation and the citation gate

`pipelines/rag/generate.py`.

- The retrieved chunks are rendered as a closed, per-request dictionary `C1..Ck` (k = 10, chosen
  because recall@10 measured 1.000 and k = 6 dropped a gold article from the candidate set).
- The model answers through strict function calling: theses with `citations` that may only contain
  candidate IDs. Internal structure (hashes, unit paths) never reaches the model.
- A deterministic resolver maps each ID to the exact citation string from the database, composed as
  `{act title}, {citation}` because the same "ст.5" exists in many acts.
- An ID outside the set is rejected; the request is regenerated at most twice; then the system
  abstains honestly. A hallucinated citation is thus an invariant violation, not a prompt failure.
- A 10 000-token context budget drops whole trailing candidates and never truncates a text.
- A review flag catches internal vocabulary ("candidate", "prompt", C-ids) leaking into user prose.

`ml/llm_client.py` adds the data-governance seatbelt: user input is wrapped with a sentinel wherever it
enters a prompt, and the external-model client refuses to send a prompt that carries the sentinel. Open
data flows freely; user data is routed to a local or zero-retention model.

## 4. API seam

`api/main.py` exposes one endpoint, `POST /api/generate`, bound to 127.0.0.1 only. Abstain is a valid
200 response; validation errors are 422; a degraded pipeline still answers with `degraded` set; a
missing generation model is 503; the worst-path timeout is 120 s (two regenerations plus reranking).
Every error carries a uniform `{error, message}` body, never a stack trace. The reranker pin is
verified at startup: drift stops the process before it binds. The trace stays under `DATA_DIR`;
only a `request_id` leaves the process. The API is built with `create_app(generate_fn=…)` so the test
suite drives it on a stub.

## 5. Evaluation

`eval/`. The rule is that the evaluation never measures itself: the reference questions were written
by the lead agent and cross-checked by five independent agent reviews, never by the model under
evaluation.

- `eval/retrieval_eval.py`: recall@k, precision@1 and MRR@k per question class (paraphrase, distinctive,
  citation) and per layer (dense, hybrid, rerank), with one fail-loud validator for the gold format.
- `eval/retrieval_baseline.py`: freezes the top-k per question and turns a lost gold hit into a red
  regression (exit 1).
- `eval/harness.py`: generation taxonomy (correct / null / wrong pick among candidates / hallucination /
  precision drift), `sufficient@k`, a lint for unbacked action verbs, a golden regression corpus where
  a mechanical case is hard-red on one mismatch, and a two-pass replay at temperature 0 that measures
  set-flip noise first and sets the red threshold above it (0.45 after measuring 0.310 with zero
  gold flips). Runs are written as JSONL with a run id; golden cases live in git.
- Stub backends make the whole harness run offline.

## 6. Collection discipline

`pipelines/politeness.py` meters per-host request rate and daily volume from a policy table, with
state on disk under a cross-process lock, so orchestrator subprocesses and worker threads share one
budget. Days are Europe/Kyiv days, frozen per process. `pipelines/freshness/` probes the sources for
new editions and keeps a registry of them. `pipelines/exitcodes.py` is the single exit-code
convention (no "exit 0 while errors happened"). `pipelines/units_ledger.py` records units per
(act, edition) so that a partial deletion or an injection into a known edition is visible even when
totals stay above their floors.

## Invariants, in one place

1. A citation names an `atom_id` that a retrieved chunk has, or it does not exist.
2. Nothing outside the edition in force on `as_of` is scored, served or cited.
3. Every layer degrades honestly and says so; no layer pretends to have run.
4. User data never reaches the external model; open data may.
5. The evaluation never measures itself, and a red gate is set above measured noise.
