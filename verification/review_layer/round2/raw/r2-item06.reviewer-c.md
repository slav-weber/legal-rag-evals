BLOCK

```json
[{"file": "api/main.py", "line": 164, "severity": "critical",
  "invariant": null,
  "defect": "main() now binds the dev server to 0.0.0.0 instead of 127.0.0.1, while the trailing comment on the same line, the module docstring and the README all still promise localhost-only.",
  "consequence": "Anyone on the same LAN/Wi-Fi (or any network the container publishes the port to) can POST /api/generate on a seam that by design has no auth, no rate limit and no CSRF protection: they burn the DeepSeek budget and write arbitrary questions into the t14 trace pool, which persists the question text.",
  "evidence": "[LIVE]",
  "proof": "python -m ruff check --no-cache --output-format concise . -> 'api\\main.py:164:27: S104 Possible binding to all interfaces / Found 1 error.', so the CI 'lint' gate (verification/gates.py GATES) is RED. api/main.py:5 still reads 'the server binds 127.0.0.1 ONLY', line 8 'dev (127.0.0.1:8000)', README.md:24 and docs/ARCHITECTURE.md:91 both say 'bound to 127.0.0.1'. Nothing in tests/test_api.py pins the bind address (TestClient never binds), so the linter is the only guard. Unrelated to the stated refactor."},
 {"file": "pipelines/rag/retrieval.py", "line": 310, "severity": "major",
  "invariant": null,
  "defect": "_ART_RE lost its article-suffix group: r'\\b(?:статт\\w*|ст)\\.?\\s*(\\d+(?:-\\d+)?)' became r'\\b(?:статт\\w*|ст)\\.?\\s*(\\d+)', so a hyphenated article number is truncated to its base number.",
  "consequence": "A citation question about «ст.210-1 КУпАП» resolves to ст.210 — a different offence — and the deterministic exact route, which exists precisely because 'a citation is an ID, not a relevance guess', serves the wrong article's leaves as the authoritative candidate #1, ahead of and never reranked against the channels.",
  "evidence": "[LIVE]",
  "proof": "python -m unittest discover -s tests -q -> 'FAIL: test_article_suffix_is_part_of_the_number (test_retrieval_offline.ExactRoute...) AssertionError: 'ст.210' != 'ст.210-1'' ; Ran 336 tests, FAILED (failures=1, skipped=1) — the CI 'unit-tests' gate is RED. Direct calls: _parse_article('стаття 210-1 КУпАП') -> 'ст.210'; _parse_article('ст. 173-2 КУпАП') -> 'ст.173'; _parse_article('ст.283-2') -> 'ст.283'. The comment one line above still documents «ст.N-M», and pipelines/rag/generate.py:40 _ARTNUM_RE still carries (?:-\\d+)?, so the two modules now disagree on what an article number is."},
 {"file": "pipelines/rag/generate.py", "line": 117, "severity": "major",
  "invariant": null,
  "defect": "dedup_candidates() dropped the act from its group key — groups.setdefault((h['act'], stem), []) became groups.setdefault(stem, []) — so candidates are grouped by article stem alone, across acts.",
  "consequence": "Hits from DIFFERENT acts that share an article number land in one group, and a container in one act subsumes the other act's norm: the loser is silently removed from the C1..Ck set, never reaches the model, and is absent from the dropped-report (which only lists empty_text and budget drops). That is the cross-act «ст.5» collision class this module's own docstring says the design exists to prevent, reintroduced one layer earlier than act_citation() can help.",
  "evidence": "[LIVE]",
  "proof": "dedup_candidates([{act:'2747-15',unit_path:'ст.5'},{act:'3543-12',unit_path:'ст.5/п.2'}]) -> n_in=2 n_out=1, kept ('2747-15','ст.5') only; the 3543-12 leaf is gone. Two containers from different acts: dedup_candidates([{act:'2747-15',unit_path:'ст.5'},{act:'8073-10',unit_path:'ст.5'}]) -> n_in=2 n_out=1. Leaves from two acts are also interleaved into one natural-order block: -> [('8073-10','ст.5/п.2'), ('2747-15','ст.5/п.10')]. The suite stays green on this: all four cases in test_generate.Dedup use the single act 'A', so no test exercises a second act."}]
```
