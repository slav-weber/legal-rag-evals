CONFIRMED

[LIVE] Building the map from the same card rows the offline test uses, against the committed fixture `tests/fixtures/rada_r_sample.txt` (it prints `3633-20` and never `3633-IX`): after the change `'3633-20' in map` is False and `seed_hits` returns `['560-2024-п']` with signal `94029cfd8511a31c`, where the pre-diff loop gave `['3633-20', '560-2024-п']` and `888bea720ea1be0f` — one false 🟡 as the baseline rebaselines, then silence on the mobilisation law.

[LIVE] `python -m unittest discover -s tests -p test_freshness_rada_matcher.py` errors with `KeyError: '3633-20'` at `amap["3633-20"] == "3633-20"` in `SeedAliasMapOffline.test_builds_both_spellings`, and that test id is listed at `verification/test_inventory.json:89`, so the ratchet fails with it.

[CODE] No caller restores the canonical key: `seed_hits` (probe.py:104) searches the feed only for the map's *keys*, probe.py:134's fallback is the alias-only `{n: n for n in SEED_ACTS}`, `chunk.py:91` looks the map up by native key so it neither needs nor re-adds the entry, and the untouched docstring directly above the changed line still says the feed uses `3633-20` and that matching only SEED_ACTS "was blind to it forever" — the author's own description claims only shared guards and readers, so this is an unintended behaviour change inside a refactor.
