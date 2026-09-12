BLOCK

```json
[{"file": "pipelines/rada/chunk.py", "line": 139, "severity": "critical",
  "invariant": "1",
  "defect": "The затв. branch was rewritten from `f\"{block_title} (затв. {num})\" if block_title else f\"затв. {num}\"` to `block_title or f\"затв. {num}\"`, which drops the block ordinal whenever the block has a title.",
  "consequence": "Two different approved blocks with the same title collide on one citation string again — 560-2024-п titles both затв.1 and затв.2 «ПОРЯДОК» (76-2023-п likewise), the exact defect fixed at acceptance 2026-07-17 (23 strings shared by 46 chunks). A citation then no longer addresses exactly one atom_id, so the structural citation gate can confirm a cited id exists but not that the string resolves to the chunk actually served.",
  "evidence": "[LIVE]",
  "proof": "`python -m unittest tests.test_chunk` → 3 failures. test_approved_block_uses_its_title: render_citation(\"затв.1/п.4\", ED, \"point\", block_title=\"ПОРЯДОК\") returns 'ПОРЯДОК п. 4 · ред. від 12.04.2026', expected 'ПОРЯДОК (затв. 1) п. 4 · ред. від 12.04.2026'. test_two_blocks_with_the_same_title_do_not_collide and test_number_is_rendered_even_for_a_lone_block fail the same way. The comment on lines 134-138 directly above the changed line still states the ordinal is 'load-bearing, not decoration' and 'Always rendered, even for a lone block', and PARSER_VERSION (line 73) still reads 't9-18.3fix  # fix: затв. number now in the citation' while the code reverts that fix."},

 {"file": "pipelines/checks/_common.py", "line": 58, "severity": "critical",
  "invariant": "4",
  "defect": "The `follow_redirects` default was flipped from False to True, which makes the `if not follow_redirects and r.is_redirect` guard on line 77 unreachable for every caller that does not pass the flag, so RadaRoutingError can no longer fire on the default path.",
  "consequence": "A 3xx from a data.rada opendata endpoint — a lost UA on the wire, or Rada's temporary anti-DDoS bounce to the human site zakon.rada.gov.ua — is now silently followed to HTML and returned as a 200. `pipelines/rada/fetch_texts.py:78` (`r = get(url)`) then takes that HTML as the edition text and returns it as the act's corpus text; `pipelines/ksu/snapshot.py:106` (`r = get(url, ua=\"OpenData\")`) sha256s it and writes it to disk plus the snapshots table as a genuine ksu-txt. This is the silent poisoning the module was written to prevent — the docstring names the 2026-07-09 'migration' false alarm that came from exactly a browser UA plus a followed 302.",
  "evidence": "[LIVE]",
  "proof": "`python -m unittest discover -s tests` → FAIL: test_rada_reachability.GetNoFollow.test_raises_rada_routing_error_on_redirect — 'RadaRoutingError not raised'; the test mocks httpx.get to return a 302 to zakon.rada.gov.ua and calls cm.get(url) with no flag. The function's own docstring on line 63 still reads '``follow_redirects`` defaults to False', and pipelines/rada/fetch_attachments.py:72 still carries the comment 'explicit opt-in (default now False)' — both now contradict the signature."},

 {"file": "pipelines/units_ledger.py", "line": 56, "severity": "major",
  "invariant": null,
  "defect": "The drift predicate was changed from `live_entries.get(k) != v` (any difference) to `live_entries.get(k, 0) < v` (fewer only), so a count that GREW inside a known edition is no longer reported.",
  "consequence": "An injection into an existing edition — the module docstring's own example, a reparse that turns quoted amendment headings into phantom host articles — passes the ledger clean. That is half the reason the ledger exists: the data-gate counters are `>=` floors, so added units are invisible to them, and this exact manifest was the only check that caught them. Deletions are still caught, so the hole is silent and one-directional.",
  "evidence": "[LIVE]",
  "proof": "`python -m unittest tests.test_units_ledger` → FAIL: test_growth_inside_a_known_edition_detected — with ledger {'3543-12|2026-07-31': 112} and live {'3543-12|2026-07-31': 113}, d['changed_or_deleted'] is {} where the test expects {'3543-12|2026-07-31': {'ledger': 112, 'db': 113}}. The test's own comment states 'a single extra unit is a count drift exactly like a missing one'."}]
```

Notes on the rest of the change (no findings): the four extractions named in the description — `_bootstrap_reference`, `_assert_model`, `_assert_cosine` in `ml/embed_index.py`, the same plus `_assert_scores`/`_assert_order` in `ml/reranker.py`, and the `_scalar`/`_insert_batch`/`_print_coverage`/`_run_build` helpers in `ml/embed_index.py` and `ml/lemma_index.py` — are behaviour-preserving as read. `_scalar(cur, sql, *params)` forwards correctly in both the zero-param and one-param call (`cur.execute(sql)` / `cur.execute(sql, (model,))`), `coverage_gap` still returns `(missing, total)` in that order, `_insert_batch` keeps the per-batch commit checkpoint, and `lemma_index._run_build` keeps the `try/except → emit(ok=0, failed=1) → raise` failure path while `embed_index._run_build` keeps the `lm_down` R-10 branch returning 1. The three defects above are all in hunks the description does not mention.

Definition of done: `python -m verification.gates` is RED — '4/5 gate(s) passed; failed: unit-tests', 336 tests with 5 failures, all five attributable to the three hunks above (3 chunk, 1 reachability, 1 units_ledger). The test-ratchet gate passes, so no test was removed or skipped to hide them.
