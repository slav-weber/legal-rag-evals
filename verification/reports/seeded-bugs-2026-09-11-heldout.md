# Seeded-bug benchmark · 2026-09-11 · heldout

**The deterministic gates caught 12 of 20 planted bugs (60 %).** The canary (H00) was caught by unit-tests, test-ratchet.

| | |
|---|---|
| Measured | 2026-09-11T13:09:14Z · git `fc5359e` · Windows · Python 3.12.13 |
| Tree | sha256 `386627c6f69cf5937a1c1c5e1c9cef836a9934a35d9093a601908886670031dd` over 128 files |
| Catalogue | `verification/seeded_bugs/catalogue_heldout.py` · sha256 `c9e01461af46ca2a99f95d72bf259607a2c5c67b49ac3ec9100224d4bae82f38` |
| Gates | unit-tests · test-ratchet · lint · eval-no-llm · eval-stub-gate (the list CI runs: `verification/gates.py`) |

## By area

| Area | Planted | Caught |
|---|---|---|
| api | 1 | 1 |
| citation gate | 1 | 0 |
| collection | 3 | 2 |
| context budget | 1 | 0 |
| data governance | 2 | 2 |
| evaluation | 4 | 2 |
| exit codes | 3 | 1 |
| parsing | 1 | 1 |
| rendering | 1 | 1 |
| retrieval | 3 | 2 |

## Every bug

| Bug | Area | Planted defect | Caught by | Evidence |
|---|---|---|---|---|
| H01 | retrieval | Temporal scope gate inverted: serves editions not yet in force | unit-tests | test_both_bounds_are_inclusive (test_retrieval_offline.ScopeClause) |
| H02 | retrieval | Exact-lookup drops the natural-order re-sort of an article's leaves | unit-tests | test_round_robin_keeps_a_small_article_in_the_top (test_retrieval_offline.ExactRoute) |
| H03 | retrieval | Reranker ordering reversed: least-relevant candidates ranked first | **missed** | — |
| H04 | context budget | Context budget skips an over-budget candidate instead of tail-dropping | **missed** | — |
| H05 | citation gate | Citation gate tolerates an out-of-set id when any valid id is cited | **missed** | — |
| H06 | data governance | User-data tripwire requires ALL fragments to be marked | unit-tests | test_1_content_string (test_user_data_tripwire.Tripwire); test_2_content_list_part (test_user_data_tripwire.Tripwire); test_3_tool_call_arguments (test_user_data_tripwire.Tripwire); test_4_top_level_string_field (test_user_data_tripwire.Tripwire); test_5_deeply_nested (test_user_data_tripwire.Tripwire); test_D_sentinel_in_dict_key (test_user_data_tripwire.Tripwire) |
| H07 | data governance | String walker fails open on uninspectable values | unit-tests | test_B_bytes_value_rejected (test_user_data_tripwire.Tripwire); test_C_set_value_rejected (test_user_data_tripwire.Tripwire); test_G_object_with_sentinel_str_rejected (test_user_data_tripwire.Tripwire); test_uninspectable_raises (test_user_data_tripwire.WalkStrings) |
| H08 | api | API binds to all interfaces instead of localhost | lint | S104 |
| H09 | exit codes | Batch exit-code reducer uses numeric max instead of severity | unit-tests | test_worst_severity_not_bitwise (test_exitcodes.Convention) |
| H10 | collection | Politeness pause removed for the bulk court registry | unit-tests | test_policy_table_per_host (test_politeness.Politeness) |
| H11 | collection | Rada daily byte cap inflated past the published limit | **missed** | — |
| H12 | collection | Units ledger stops flagging deleted editions | unit-tests | test_edition_vanished_detected (test_units_ledger.LedgerDiff) |
| H13 | rendering | Citation drops the block ordinal, colliding two approved documents | unit-tests | test_number_is_rendered_even_for_a_lone_block (test_chunk.ApprovedBlockCitationCollision); test_two_blocks_with_the_same_title_do_not_collide (test_chunk.ApprovedBlockCitationCollision); test_approved_block_uses_its_title (test_chunk.CitationRender) |
| H14 | parsing | Duplicate-path dedup no longer prefers the substantive unit | unit-tests | test_empty_husk_yields_the_canonical_path_to_the_live_article (test_parse_structure_t9.DedupePrefersSubstantive) |
| H15 | evaluation | Gate no longer reds on a citation-gate breach | unit-tests | test_hallucination_alone_turns_the_gate_red (test_harness.CliGate) |
| H16 | evaluation | Recall hit-test prefix-matches, inflating recall | unit-tests | test_a_longer_number_is_a_different_article (test_gold_rank.GoldRank) |
| H17 | evaluation | Replay-noise threshold raised far above the measured floor | **missed** | — |
| H18 | evaluation | Retrieval-baseline regression downgraded to a non-fatal warning | **missed** | — |
| H19 | exit codes | Reachability RED reported as a planned skip | **missed** | — |
| H20 | exit codes | Card fetch exits OK despite fetch failures | **missed** | — |

## Missed

- **H03** Reranker ordering reversed: least-relevant candidates ranked first. While refactoring the rerank step an agent flips reverse=True to reverse=False, so the cross-encoder orders candidates worst-first and the gold article is pushed down or out of the top-k handed to generation.
- **H04** Context budget skips an over-budget candidate instead of tail-dropping. An agent 'packs the budget better' by changing break to continue, so a high-ranked large candidate is silently skipped while smaller lower-ranked ones fill in — C1..Ck are no longer the contiguous top set, and the dropped-report (which assumes a prefix) misreports what was cut.
- **H05** Citation gate tolerates an out-of-set id when any valid id is cited. Aiming to 'not waste a good answer', an agent makes the out-of-set rejection conditional on there being no valid citation at all (if invalid and not resolved), so a dovidka that mixes a real candidate with a fabricated C-id is accepted and served instead of being regenerated — the code no longer arbitrates every id.
- **H11** Rada daily byte cap inflated past the published limit. An agent 'gives the collector headroom' and raises CAP_BYTES to 800 MB, breaking the self-cap that keeps the daily Rada download under the source's published 200 MB/day limit.
- **H17** Replay-noise threshold raised far above the measured floor. Finding the replay gate 'too flaky', an agent bumps the set-flip threshold to 0.95, well above the measured 0.310 noise floor, so genuine temperature-0 instability no longer trips the two-pass replay red.
- **H18** Retrieval-baseline regression downgraded to a non-fatal warning. An agent 'stops the baseline from failing CI on churn' by returning 0 from the lost-gold branch, so a question that used to retrieve its gold norm and now does not is printed but no longer fails the regression check.
- **H19** Reachability RED reported as a planned skip. An agent 'reduces noise' from the reachability watcher by mapping RED to SKIP, so a genuine routing/migration anomaly (data.rada serving HTML instead of JSON) exits 2 and cron treats a real source breakage as a benign defer.
- **H20** Card fetch exits OK despite fetch failures. An agent decides the cumulative editions floor is enough and drops failed_acts from the exit condition, so swallowed per-card fetch failures exit 0 as long as the floor is already met — exit 0 while errors happened.

## Reproduce

```bash
uv sync
uv run python -m verification.seeded_bugs.run --catalogue verification/seeded_bugs/catalogue_heldout.py --no-write
```
