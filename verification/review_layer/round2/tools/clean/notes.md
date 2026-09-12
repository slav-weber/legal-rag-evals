# Notes on the six changes

Base: `legal-rag-evals` at `129470d`. Each change was made in its own fresh copy of the tree
(`git archive 129470d | tar -x`), so the six patches are independent: no two touch the same file.
Line counts below are `git diff --numstat`, counted as insertions + deletions.

Verification for every change, in its own copy:

* `uv run --frozen python -m verification.gates` → `GREEN: 5/5 gate(s) passed`
* a behaviour probe run against the pristine tree and against the changed tree, the two JSON dumps
  compared with `cmp`. The probes live in `review_bench2/_checks/k0N_probe.py`, their outputs in
  `_checks/k0N_base.json` / `_checks/k0N_new.json`, and the driver that reruns everything is
  `_checks/verify_all.sh`.
* `git apply --check` of the patch against a fresh archive of `129470d` (`review_bench2/_verify`).

Three things the probes normalise, because they are not behaviour: the absolute path of the tree
(it appears in one harness message), the wall clock (rows whose SQL parameters carry
`datetime.now(timezone.utc)`), and `PYTHONHASHSEED`, which is pinned to 0 for both runs — the
unchanged code builds `list({...})` over a set of content hashes, so that list's order is
randomised per process in the base tree too. The first K01 run surfaced this before the seed was
pinned; the only difference between the two dumps was that list's order.

`verification/seeded_bugs/`, `verification/reports/` and `verification/review_layer/` were not
opened or searched in any copy.

---

## K01 — retrieval + generation (large, 234 lines, 2 files)

| file | +/- | = |
|---|---|---|
| `pipelines/rag/retrieval.py` | +84 / -55 | 139 |
| `pipelines/rag/generate.py` | +62 / -33 | 95 |

The six shared candidate columns became one `_CANDIDATE_COLUMNS` constant and one `_hit()` row
builder, used by `dense`, `fts`, `lemma` and `exact_lookup`, which each had their own copy of the
same `SELECT` prefix and the same seven-key dict comprehension. `(act, unit_path, in_force_from)`
— the citable identity — became `_identity()`, used by RRF fusion and by the exact-route merge, the
two places that must agree on what counts as the same norm. `search()`'s reranking and its
exact-first merge moved into `_rerank_channels()` and `_merge_exact_first()`. In `generate.py`,
`build_candidates()` gained `_chunk_meta()` / `_enrich()`, and `generate()` gained
`_attempt_record()`, `_gate_problem()` and `_append_rejection()`.

Compared before/after (59 observations): the exact SQL string and parameter dict each channel
issues against a recording fake cursor, and the rows they return; RRF fusion output under the
calibrated weights; `hybrid()` with a failing channel and the `RAG_DEBUG` stdout it prints;
`search()` reranked, with the reranker raising `RerankerUnavailable`, and with exact hits merged in
front; the scope clause, natural-sort key, query normalisation, article parsing, act mentions and
citation binding; `dedup_candidates`, `_apply_budget`, `build_candidates`, `resolve_citations`,
`prose_lint`; the rendered dovidka HTML for a full answer, an abstain and an empty result; seven
end-to-end `generate()` runs (clean, retry-then-valid, never-valid, citation-free, model abstain,
no candidates, degraded meta) including the exact message list handed to the model on the last
call; and the bytes of the trace file.

The SQL is byte-identical, not merely equivalent: `_CANDIDATE_COLUMNS` reproduces the original
string including its interior whitespace, and the probe compares the statements as strings.

## K02 — evaluation harness (large, 226 lines, 2 files)

| file | +/- | = |
|---|---|---|
| `eval/harness.py` | +93 / -76 | 169 |
| `eval/retrieval_eval.py` | +39 / -18 | 57 |

`_iter_jsonl()` in `retrieval_eval` is now the one reader for JSONL gold: `_load_gold` uses it, and
the harness imports it for `load_golden` and `_acts_from_gold`, both of which had their own
read/split/skip-blank/`json.loads` loop. It yields the 1-based line number, so the fail-loud
messages still point at the real line of the file. `_load_gold` split into `_expected()` and
`_annotations()`. In the harness, the per-question counter update became `_tally()` (the overall
bucket and the class bucket are now counted by the same code), the persisted run and noise files
share `_write_jsonl()`, the offline stubs share `_stub_result()`, and `main()` gained
`_known_act_set()` and `_run_fn()`.

`_run_fn` builds its stub table inside the function, on purpose: `tests/test_harness.py` patches
`H._stub_run` on the module and then calls `main()`, so a module-level table would freeze the
original function and defeat that test.

Compared before/after (58 observations): the loaded gold for all three committed gold files; six
`_parse_citation` cases and four malformed-gold files, by exact error message; `_gold_rank`;
`_run_mode` for all three modes with retrieval faked, including its printed block; mechanical
fields, taxonomy, sufficiency and three `score()` runs; the committed golden corpus and four
malformed golden files; `check_golden`, `run_golden`; every stub backend including `_stub_flip`'s
module-global counter across three calls; three `measure_noise` runs; the exact bytes of the run
and noise artifacts; and nine CLI invocations (`--no-llm`, gate on stub / stub-abstain /
stub-hallucinate, score, noise on stub-flip, the stub-flip guard, empty gold, `--known-acts`) with
their exit codes and stdout.

## K03 — freshness layer (large, 199 lines, 3 files)

| file | +/- | = |
|---|---|---|
| `pipelines/freshness/probe.py` | +58 / -28 | 86 |
| `pipelines/freshness/rada_backstop.py` | +46 / -35 | 81 |
| `pipelines/freshness/rada_sample.py` | +18 / -14 | 32 |

The "is this really a plain r.txt feed" guard was spelled out twice, in `probe.probe()` and in
`rada_sample.main()`; it is now `is_plain_rtxt()`. The source_checks trail had two writers of the
same `INSERT` and two spellings of the same "changed vs the last successful signal" test; they are
now `record_check()` and `changed_since()` in `probe.py`, which the backstop imports (it already
imports `_decode_rada` / `_get` / `seed_alias_map` from there for the sampler). `probe.main()`
gained `_check_source()` and `_status()`; the backstop's `run()` gained `_collect()`, `_signal()`
and `_note()`; the sampler gained `_record_snapshot()`.

`rada_backstop._last_signal(conn)` keeps its name and one-argument signature — `tests/
test_rada_backstop.py` patches it — and now delegates to `probe._last_signal(conn, SOURCE_ID)`. The
two SQL strings were already character-identical once joined. `rada_sample` lost its `import re`,
which the guard was its only user of.

Compared before/after (56 observations): 19 probe cases covering every `probe_kind` and every
error path (403, HTML captcha, short body, no nreg token, honest none, CKAN with and without a ZIP
resource, a missing `package_id`, HF 404 / no sha / on-pin / off-pin, listing 500, id-regex,
explicit encoding, page hash, manual) plus two exception paths; five `_decode_rada` cases; the seed
matcher and alias map; `_last_signal`; `_upsert_sources`' SQL and its orphan report; the written
`freshness.md`; two full `main()` runs (one with the backstop raising) with their SQL, stdout and
exit code; `card_state`, `compare`, the N-day gate, and five backstop `run()` shapes (complete,
partial, all-error, gate closed, no budget); and three sampler runs with the files they write.

## K04 — model pins and index builders (large, 241 lines, 3 files)

| file | +/- | = |
|---|---|---|
| `ml/embed_index.py` | +77 / -39 | 116 |
| `ml/lemma_index.py` | +42 / -22 | 64 |
| `ml/reranker.py` | +42 / -19 | 61 |

Both `check_pin()`s were one long function doing bootstrap, name check, drift check and (for the
reranker) an ordering check; each is now a composition of named assertions —
`_bootstrap_reference`, `_assert_model`, `_assert_scores` / `_assert_cosine`, `_assert_order`.
`embed_index` and `lemma_index` each had the same "one cell out of one query" idiom twice inside
`coverage_gap`; that is `_scalar()` now, and each builder's per-batch `executemany` + `commit`
became `_insert_batch()`. Both `main()`s gained `_print_coverage()` and `_run_build()`.

Compared before/after (65 observations): the reranker pin at tolerance, just over it, on a hard
drift, on a name mismatch, and bootstrapped into a temp file (whose bytes are compared); pin
caching across two `rerank()` calls, counted by call; `_load` failing through a fake
`FlagEmbedding`; five reranker CLI branches including the unavailable path and its stderr;
`_l2`, `_cosine`, `embed_passages`, `embed_query`, a wrong-dimension vector, the embedder pin OK,
drifted and bootstrapped; `missing_hashes` / `coverage_gap` SQL and parameters; three `build()`
outcomes (work to do, already complete, LM down) with the rows written; four embed CLI branches;
`lemmatize` on four inputs through the real pymorphy3; and the lemma builder's SQL, batches and
CLI, including the crash path that still emits a summary.

One honest gap: the probe case I named `order_broken` trips the score-drift assertion before the
ordering one, because the two reference scores are about six logits apart and the tolerance is 0.5
— a swap large enough to break the ordering is always large enough to break the scores first.
`_assert_order` is therefore covered only through the relevant/irrelevant figures in the pin-OK
message, which the probe does compare.

## K05 — LLM client (medium, 103 lines, 1 file)

| file | +/- | = |
|---|---|---|
| `ml/llm_client.py` | +68 / -35 | 103 |

`getattr(usage, "...", 0) or 0` appeared seven times across two result builders; it is now
`_usage_counts()`. The `extra_body` reasoning switch was written out at both DeepSeek entry points
and is now `_thinking()`. `_strictify_schema` had its object-level work inline inside the recursion
and now calls `_strictify_object()`. The forced tool call's absence and its truncated-JSON parse
became `_first_tool_call()` and `_tool_args()`, so `call_tool_deepseek` reads as guard → request →
parse.

Compared before/after (30 observations): every call the SDK would receive — constructor keywords,
`chat.completions.create` keywords (model, messages, temperature, max_tokens, tools, tool_choice,
extra_body), `embeddings.create` and `models.list` — recorded from a stand-in client, together with
the returned dataclasses; `chat` with and without usage, with an empty content and with no echoed
model; `embed` for one and many, and with no model configured; both DeepSeek entry points including
the no-key, marked-payload, no-tool-call, truncated-JSON, empty-arguments and missing-cache-field
paths; thirteen tripwire payloads by verdict; six `_walk_strings` and six `_message_texts` cases;
seven schema shapes through `_strictify_schema`; and a check that the caller's tool dict is
unchanged after the call.

## K06 — Rada fetch counters (medium, 82 lines, 2 files)

| file | +/- | = |
|---|---|---|
| `pipelines/rada/fetch_texts.py` | +35 / -26 | 61 |
| `pipelines/ksu/snapshot.py` | +13 / -8 | 21 |

`fetch_texts.main()` carried six loose counters plus a `budget_stopped` flag through a nested loop;
they are now a small `_Tally` dataclass, which also gives the run-wide stop flag a name. The КСУ
snapshotter's `snapshots` INSERT + commit became `_record_snapshot()`.

What I was unsure about, and got wrong first: this change originally also moved the two-part
`remaining() < DEFER_RESERVE or not can_spend(est)` test — spelled out identically in both
collectors — into a `budget.should_defer()` helper, and tidied `_seed_today`'s double `stat()`
call. That took the unit-tests gate RED: `tests/test_fetch_texts.py` and
`tests/test_ksu_snapshot_exit.py` both substitute a hand-written fake budget object exposing only
`CAP_BYTES`, `used`, `remaining`, `can_spend` and `add`, so any new attribute the collectors call
on that module does not exist during the test. The helper is out, the budget test stays inline at
both call sites, and `pipelines/rada/budget.py` is untouched by this patch.

Compared before/after (34 observations): the real budget module against a throwaway data
directory — fresh, after two `add`s, seeded from files on disk, near the cap and at the cap, with
the ledger file's contents; `edition_selector` for all four flag combinations; `fetch_txt` on 200,
404, retry-then-success, persistent 5xx and an empty body, each with the pause/request/backoff
timeline it produced; eight `fetch_texts.main()` runs (default, `--current`, `--since`, all-404,
mojibake, persistent transient, budget-deferred, two acts) with exit code, stdout, the files
written and their contents, the SQL issued and the budget ledger afterwards; `label`, `exit_code`
and `already_done`; and six `ksu.snapshot.main()` runs (clean, all already done, all-404, mojibake,
budget-deferred, empty body) with the same set of observables.
