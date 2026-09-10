# Results

All numbers are measurements on the private corpus of the system this repository was extracted from:
11 Ukrainian acts, 4 706 citable chunks, 4 680 embeddings (606 container chunks are excluded from the
indexable set), 29 reference questions (`eval/data/retrieval_gold_v0.jsonl`: 13 paraphrase,
10 distinctive, 6 citation). Each table names the date, the code and the model that produced it.

## 1. Retrieval, re-measured with this code (2026-09-10)

Run: `python -m eval.retrieval_eval --gold eval/data/retrieval_gold_v0.jsonl --mode all --k 10`,
embedding model `text-embedding-bge-m3` (LM Studio), reranker `BAAI/bge-reranker-v2-m3` (pinned),
PostgreSQL 17 with pgvector. Captured output: `eval/results/2026-09-10_retrieval_gold29.txt`.

| Class (n) | Layer | recall@10 | p@1 | MRR@10 |
|---|---|---|---|---|
| paraphrase (13) | dense | 1.000 | 0.923 | 0.962 |
| paraphrase (13) | hybrid (RRF) | 1.000 | 0.923 | 0.962 |
| paraphrase (13) | rerank (+ exact lookup) | 1.000 | 0.923 | 0.938 |
| distinctive (10) | dense | 1.000 | 1.000 | 1.000 |
| distinctive (10) | hybrid (RRF) | 1.000 | 1.000 | 1.000 |
| distinctive (10) | rerank (+ exact lookup) | 1.000 | 0.900 | 0.950 |
| citation (6) | dense | 0.167 | 0.000 | 0.019 |
| citation (6) | hybrid (RRF) | 0.167 | 0.000 | 0.019 |
| citation (6) | rerank (+ exact lookup) | **1.000** | **1.000** | **1.000** |

Reading: the exact-lookup route is what closes the citation class; the reranker itself costs one
first-place hit on the distinctive class (0.900 vs 1.000) and a little MRR on paraphrase, which is
the honest price of reordering a set that dense retrieval already ranked well on this corpus.

## 2. Retrieval acceptance measurement (2026-07-19, private pipeline)

Same corpus and questions, measured when each layer was added. Hybrid here is the equal-weight
fusion before calibration.

| Class (n) | Dense | Hybrid, equal weights | Rerank + exact lookup |
|---|---|---|---|
| paraphrase (13) | recall 1.000 · p@1 0.846 · MRR 0.904 | 1.000 · 0.769 · 0.865 | 1.000 · 0.846 · 0.887 |
| distinctive (10) | 1.000 · 0.900 · 0.950 | 1.000 · 0.800 · 0.900 | 1.000 · 0.900 · 0.950 |
| citation (6) | 0.167 · 0.000 · 0.017 | 0.167 · 0.000 · 0.017 | 1.000 · 1.000 · 1.000 |

Ablations recorded at the time:

- RRF weight calibration (dense 2.0, FTS 0.5, lemma 0.5) restored hybrid precision@1 on paraphrase
  questions to dense parity (0.769 → 0.846). The September re-measurement above shows 0.923 for both.
- Container chunks excluded from the indexable set: distinctive p@1 0.900 → 1.000, paraphrase p@1
  0.846 → 0.923, recall unchanged.
- The citation class failed structurally before the exact-lookup route: no chunk of the corpus
  contains the literal phrase "стаття 210", so neither embeddings nor full-text search can find it.

The July acceptance table was produced by a working script that was never committed; the committed
`eval/retrieval_eval.py` reproduces the same per-class metrics, which is what the September run shows.

## 3. Generation acceptance (2026-07-19, private pipeline, external model)

Run: `python -m eval.harness --backend live`, 29 reference questions, k = 10 candidates, generation
model `deepseek-v4-flash` through strict function calling.

| Metric | Value |
|---|---|
| correct | 29 / 29 |
| null (no citation where one was expected) | 0 |
| wrong pick among candidates | 57 extra cited candidates flagged, 0 wrong gold |
| hallucination (citation outside the candidate set) | 0 |
| abstain | 0 |
| precision-drift signals (correct article, drifting wording) | 5 |
| sufficient@10 | 29 / 29 |
| action verbs without a backing citation | 2 |
| act-ambiguous citations | 0 |

Replay noise at temperature 0 (two passes, `--mode noise`): set-flip rate 0.310, gold-citation flips
0. The red threshold of the noise gate (0.45) was set only after this measurement, at roughly 1.45×
the measured rate, so the gate cannot be tripped by the model's own nondeterminism on a stable gold
citation.

## 4. What the numbers do not show

- 29 questions over 11 acts is a reproducible measurement of a small corpus, not a benchmark. The
  classes were chosen to expose known failure modes (paraphrase, distinctive wording, bare article
  citations), not to be representative of user traffic.
- The reference questions were written by the lead agent of the project and cross-checked by five
  independent agent reviews; they were not written or validated by lawyers. The precision-drift
  signals are a wording-level review flag, not a legal judgement.
- Generation numbers are a single acceptance run from July 2026 on the private pipeline. Only the
  retrieval layer was re-measured with this repository's code in September 2026.
- "correct" means the gold article was cited; it does not measure the quality of the prose or whether
  the answer would satisfy a lawyer.
- The reranker's benefit is visible only on the citation class here; on this corpus dense retrieval
  already ranks the other classes well, so the reranker's value must be re-measured on a larger corpus
  before it is credited.
