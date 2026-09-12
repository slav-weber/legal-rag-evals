BLOCK

```json
[{"file": "api/main.py", "line": 164, "severity": "critical",
  "invariant": null,
  "defect": "The dev server bind was changed from 127.0.0.1 to 0.0.0.0 while the comment on the same line, the module docstring and the docs all still say localhost only.",
  "consequence": "main() publishes POST /api/generate on every network interface. The seam has no auth, no rate limit and no CSRF by explicit design (docstring line 5), so anyone reachable on the LAN can drive unbounded DeepSeek generation on the operator's API key and cause questions to be persisted to $DATA_DIR traces.",
  "evidence": "[CODE]",
  "proof": "api/main.py:164 `uvicorn.run(app, host=\"0.0.0.0\", port=8000)          # localhost ONLY (dev)` — the trailing comment contradicts the code it annotates. Four other statements still assert the old bind: api/main.py:5 'the server binds 127.0.0.1 ONLY', api/main.py:8 '# dev (127.0.0.1:8000)', README.md:24 'bound to 127.0.0.1', docs/ARCHITECTURE.md:91 'bound to 127.0.0.1 only'. grep for 0.0.0.0 over the tree returns this line alone; no test pins the bind, so the suite does not notice."},

 {"file": "pipelines/rag/generate.py", "line": 117,
  "severity": "major",
  "invariant": "1",
  "defect": "dedup_candidates lost the act from its grouping key — `groups.setdefault((h[\"act\"], stem), [])` became `groups.setdefault(stem, [])` — so identically-numbered articles from DIFFERENT acts now land in one group and subsume each other.",
  "consequence": "A question spanning two acts that both have an «ст.5» silently loses one act's norm before the candidate set is built. The model is then handed only one act's article and either cites the wrong act's norm or abstains for lack of grounds, and the operator sees nothing: dedup runs before the dropped-report is computed, so the lost norm appears in neither dropped['empty_text'] nor dropped['budget'] (n_before counts post-dedup hits).",
  "evidence": "[LIVE]",
  "proof": "Ran against the tree: `G.dedup_candidates([{act:'8073-10',unit_path:'ст.5'}, {act:'2747-15',unit_path:'ст.5/ч.2'}])` → out `[('8073-10','ст.5')]`; DROPPED `[('2747-15','ст.5/ч.2')]` — a different act's norm removed as if it were a leaf of the first act's container. Same with two bare `ст.5` rows from the two acts → one survives. The function's own docstring (line 110) still specifies 'Per (act, article-stem) group', and the module docstring (line 12) names this exact class as 'the source of the 78 cross-act «ст.5» collisions'. Uncovered by tests: every fixture in tests/test_generate.py::Dedup uses the single act 'A', so `discover -p test_generate.py` is 43 tests OK with the bug in place."},

 {"file": "pipelines/rag/retrieval.py", "line": 310,
  "severity": "major",
  "invariant": null,
  "defect": "_ART_RE dropped its suffix group: `(\\d+(?:-\\d+)?)` became `(\\d+)`, so a hyphenated article number «ст.210-1» is parsed as «ст.210».",
  "consequence": "The deterministic citation route — the one route that is authoritative by design and never reranked — resolves a question about ст.210-1 КУпАП to a different article, ст.210, and serves that article's leaves as the top candidates. The user gets a confident answer built on the wrong norm. Ukrainian codes use these superscript articles heavily (ст.173-2, ст.283-2), and generate.py:40 _ARTNUM_RE still carries the suffix, so the prose lint and the retrieval route now disagree about what an article number is.",
  "evidence": "[LIVE]",
  "proof": "Existing test fails: `python -m unittest discover -s tests -p test_retrieval_offline.py -q` → FAIL test_retrieval_offline.ExactRoute.test_article_suffix_is_part_of_the_number, AssertionError: 'ст.210' != 'ст.210-1'. Whole suite: Ran 336 tests, FAILED (failures=1, skipped=1) — this one. Direct calls: _parse_article('Що передбачає стаття 210-1 КУпАП?') → 'ст.210'; ('ст. 173-2 КУпАП') → 'ст.173'; ('ст.283-2') → 'ст.283'. _citations(None,'ст.210-1 КУпАП') → [('8073-10','ст.210')], i.e. the truncated article is what gets bound to the act and queried. The comment directly above the regex (line 309) still documents '«ст.N-M» → the digits'."}]
```

Note on scope: the three defects above are all outside the change the author described. The refactor itself — `_CANDIDATE_COLUMNS`/`_hit`/`_identity`, `_rerank_channels`, `_merge_exact_first`, and the `_chunk_meta`/`_enrich`/`_attempt_record`/`_gate_problem`/`_append_rejection` extractions — is behaviour-preserving as far as I could check, including the `return merged[:k]` → `return merged` change, which is equivalent because `_merge_exact_first` already slices to k.
