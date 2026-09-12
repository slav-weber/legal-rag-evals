BLOCK

```json
[{"file": "pipelines/rada/chunk.py", "line": 139, "severity": "critical",
  "invariant": "1",
  "defect": "The затв. branch now renders `block_title or f'затв. {num}'`, dropping the block ordinal whenever the block has a title, so two different approved blocks with the same title render one identical citation string.",
  "consequence": "A citation no longer addresses exactly one atom_id: in 560-2024-п and 76-2023-п both затв.1 and затв.2 are titled ПОРЯДОК, so the previously fixed acceptance defect returns (23 citation strings shared by 46 chunks) and a user following a cited string cannot tell which approved block the answer came from; code can no longer arbitrate the cited ID to a single atom.",
  "evidence": "[LIVE]",
  "proof": "render_citation('затв.1/п.4', date(2026,4,12), 'point', block_title='ПОРЯДОК') -> 'ПОРЯДОК п. 4 · ред. від 12.04.2026' and render_citation('затв.2/п.4', ...) -> the same string, byte for byte. The comment on lines 134-138 directly above the changed line states the opposite rule (Always rendered, even for a lone block). Suite: 3 failures — test_chunk.CitationRender.test_approved_block_uses_its_title ('ПОРЯДОК п. 4 …' != 'ПОРЯДОК (затв. 1) п. 4 …'), test_chunk.ApprovedBlockCitationCollision.test_two_blocks_with_the_same_title_do_not_collide, test_chunk.ApprovedBlockCitationCollision.test_number_is_rendered_even_for_a_lone_block."},

 {"file": "pipelines/checks/_common.py", "line": 58,
  "severity": "major",
  "invariant": null,
  "defect": "The `follow_redirects` default was flipped from False to True, which makes the redirect tripwire on line 77 (`if not follow_redirects and r.is_redirect`) unreachable for every caller that does not pass the flag explicitly.",
  "consequence": "A data.rada opendata 3xx (lost User-Agent, or Rada's anti-DDoS bounce to the human site zakon.rada.gov.ua) is now silently followed instead of raising RadaRoutingError, so a JSON/text caller stores zakon HTML as if it were the resource. pipelines/rada/fetch_texts.py:78 calls `get(url)` bare and its caller only checks `status == 200`, so the followed HTML page is returned as the act edition text and poisons the corpus; the same applies to pipelines/ksu/snapshot.py:106 and to every get_json/get_text caller (_common.py:87 and :94, used by pipelines/rada/fetch_cards.py and pipelines/freshness/rada_backstop.py). This is the exact 2026-07-09 false-alarm/poisoning mode the RadaRoutingError docstring on lines 31-39 says must never be followed.",
  "evidence": "[LIVE]",
  "proof": "tests/test_rada_reachability.GetNoFollow.test_raises_rada_routing_error_on_redirect fails: a mocked 302 to https://zakon.rada.gov.ua/laws/card/x.json through cm.get('https://data.rada.gov.ua/laws/card/x.json') raises nothing — AssertionError: RadaRoutingError not raised. The function's own docstring on line 63 still reads 'follow_redirects defaults to False' and pipelines/rada/fetch_attachments.py:72 still comments 'explicit opt-in (default now False)', so both are now false."},

 {"file": "pipelines/units_ledger.py", "line": 56,
  "severity": "major",
  "invariant": null,
  "defect": "The diff predicate was weakened from `live_entries.get(k) != v` to `live_entries.get(k, 0) < v`, so a count that GREW inside a known edition is no longer reported in `changed_or_deleted` — only shrinkage is.",
  "consequence": "An injection into a known edition (for example a reparse that turns quoted amendment headings into phantom host articles) passes the gate silently. The module docstring says this ledger exists precisely because the data-gate counters are `>=` floors that miss that case, so after this change nothing detects it at all, and the operator gets a green gate over a corrupted units table. A ledger entry recorded as 0 that then vanishes from the DB is also no longer flagged.",
  "evidence": "[LIVE]",
  "proof": "diff({'a': 112}, {'a': 113}) -> {'changed_or_deleted': {}, 'new_editions': []} (should report the drift); diff({'a': 112}, {'a': 100}) -> {'changed_or_deleted': {'a': {'ledger': 112, 'db': 100}}} (shrinkage still caught); diff({'a': 0}, {}) -> {'changed_or_deleted': {}}. Suite: tests/test_units_ledger.LedgerDiff.test_growth_inside_a_known_edition_detected fails — AssertionError: {} != {'3543-12|2026-07-31': {'ledger': 112, 'db': 113}}."}]
```
