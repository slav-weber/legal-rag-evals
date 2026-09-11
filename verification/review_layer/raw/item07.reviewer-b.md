CONCERNS

```json
[{"file": "ml/reranker.py", "line": 145, "severity": "minor",
  "invariant": null,
  "defect": "No test exercises the new refusal branch, which raises SystemExit when the reference has no pair with the requested tag, and no test fails without the change. AGENTS.md's definition of done asks for exactly that evidence.",
  "consequence": "A later edit could bring back the bare next(), so StopIteration or KeyError escapes check_pin again, or could let a reference without a tagged pair pass. Either would ship with every gate green. The claim that such a reference is reported as a broken pin rests only on the author's word.",
  "evidence": "[LIVE]",
  "proof": "With the patch: python -m unittest discover -s tests -p test_reranker.py -v -> Ran 9 tests, OK (skipped=1). The same suite with the pre-change body swapped in (reranker._tag_index replaced by a function returning next(i for i, p in enumerate(pairs) if p['tag'] == tag)) -> ran 9, failures 0, errors 0, skipped 1. So the suite cannot tell the old code from the new. No file under tests/ references _tag_index, and the Pin tests call check_pin only against the committed reference, which has both tags. The new behaviour itself is correct. Probe with mocks only (REFERENCE_PATH replaced by an in-memory object, _score_pairs returning the committed scores), new vs old: pairs [] -> SystemExit (reranker pin broken: reranker_reference.json has no 'relevant' pair ...) vs StopIteration; only the relevant pair -> SystemExit (no 'irrelevant' pair) vs StopIteration; relevant pair without its tag key, listed first -> SystemExit vs KeyError 'tag'; committed reference -> pin OK in both. API startup (create_app with verify_pin raising from _tag_index([], 'relevant')) refuses in both cases: the new code gives RuntimeError: reranker pin drift — refusing to start: reranker pin broken: ..., the old code gives RuntimeError: async generator raised StopIteration. ruff check on ml/reranker.py: All checks passed."}]
```
