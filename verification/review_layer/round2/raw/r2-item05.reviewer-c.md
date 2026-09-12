BLOCK

```json
[{"file": "pipelines/rada/chunk.py", "line": 139, "severity": "major",
  "invariant": null,
  "defect": "The `затв` branch now renders `block_title or f\"затв. {num}\"`, dropping the `(затв. N)` ordinal whenever a block title exists, which contradicts the comment three lines above it that the number is rendered ALWAYS, even for a lone block.",
  "consequence": "Two different approved blocks that share a title collide on one citation string again — in 560-2024-п both затв.1 and затв.2 are titled «ПОРЯДОК», so «ПОРЯДОК п. 4» addresses two different atoms; the documented regression of 23 citation strings shared by 46 chunks returns and the structural citation gate can no longer resolve a citation to exactly one atom_id.",
  "evidence": "[LIVE]",
  "proof": "python -m unittest tests.test_chunk -> FAILED (failures=3): test_approved_block_uses_its_title 'ПОРЯДОК п. 4 · ред. від 12.04.2026' != 'ПОРЯДОК (затв. 1) п. 4 · ред. від 12.04.2026'; test_two_blocks_with_the_same_title_do_not_collide same mismatch for затв.1/затв.2; test_number_is_rendered_even_for_a_lone_block 'Наказ · ред. від 12.04.2026' != 'Наказ (затв. 1) · ред. від 12.04.2026'."},

 {"file": "pipelines/checks/_common.py", "line": 58, "severity": "major",
  "invariant": null,
  "defect": "The `follow_redirects` default flipped from False to True, so the guard `if not follow_redirects and r.is_redirect` on line 77 is dead for every caller that does not pass the flag, while the docstring on line 63 still states the default is False.",
  "consequence": "A data.rada 3xx that routes an opendata request to the human HTML site zakon.rada.gov.ua is now followed silently and returned as a 200: fetch_txt (pipelines/rada/fetch_texts.py:78) takes the `status == 200` branch and stores the HTML page as the statute edition text, ksu/snapshot.py:106 does the same for a КСУ decision, and fetch_cards.py:96 parses HTML as the act card. This is exactly the lost-UA / anti-DDoS bounce that produced the 2026-07-09 phantom «API migration», which RadaRoutingError was added to surface and never follow.",
  "evidence": "[LIVE]",
  "proof": "python -m unittest tests.test_rada_reachability -> FAILED (failures=1): test_raises_rada_routing_error_on_redirect, 'AssertionError: RadaRoutingError not raised' — cm.get('https://data.rada.gov.ua/laws/card/x.json') against a mocked 302 to zakon.rada.gov.ua returns the response instead of raising."},

 {"file": "pipelines/units_ledger.py", "line": 56, "severity": "major",
  "invariant": null,
  "defect": "The drift predicate changed from `live_entries.get(k) != v` to `live_entries.get(k, 0) < v`, so only a shrinking unit count is reported and an edition whose count grew is no longer flagged.",
  "consequence": "An injection into an already-known (act, edition) — e.g. a reparse that turns quoted amendment headings into phantom host articles — passes the ledger gate green. The ledger exists precisely because the data-gate counters are `>=` floors that cannot see growth inside a known edition, so this removes the only check covering that case while deletion detection still works, making the gate look healthy.",
  "evidence": "[LIVE]",
  "proof": "python -m unittest tests.test_units_ledger -> FAILED (failures=1): test_growth_inside_a_known_edition_detected, 'AssertionError: {} != {\\'3543-12|2026-07-31\\': {\\'ledger\\': 112, \\'db\\': 113}}' — a 112->113 unit injection yields an empty changed_or_deleted."}]
```
