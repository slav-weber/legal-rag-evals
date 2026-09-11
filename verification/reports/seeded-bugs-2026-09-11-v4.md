# Seeded-bug benchmark · 2026-09-11 · v4

**The deterministic gates caught 17 of 20 planted bugs (85 %).** The canary (W00) was caught by unit-tests, test-ratchet, eval-no-llm, eval-stub-gate.

| | |
|---|---|
| Measured | 2026-09-11T23:06:51Z · git `78ac935` · Windows · Python 3.12.13 |
| Tree | sha256 `0a2a5e77a8d8deff28eb8a1960965d49e8861c47611906b839f9596cb4fa53ec` over 237 files |
| Catalogue | `verification/seeded_bugs/catalogue_v4.py` · sha256 `787ca144e5dd12dfd07315da153809bb5bb0bafb004fd266d336606d4f217875` |
| Gates | unit-tests · test-ratchet · lint · eval-no-llm · eval-stub-gate (the list CI runs: `verification/gates.py`) |

## By area

| Area | Planted | Caught |
|---|---|---|
| api | 1 | 1 |
| candidates | 1 | 0 |
| chunking | 1 | 1 |
| citation gate | 1 | 1 |
| collection | 2 | 2 |
| context budget | 1 | 1 |
| data governance | 1 | 1 |
| evaluation | 3 | 2 |
| exit codes | 2 | 2 |
| freshness | 1 | 1 |
| ledger | 1 | 1 |
| parsing | 2 | 1 |
| retrieval | 3 | 3 |

## Every bug

| Bug | Area | Planted defect | Caught by | Evidence |
|---|---|---|---|---|
| W01 | retrieval | Scope gate drops the in_force_from bound: editions not yet in force are served | unit-tests | test_both_bounds_are_inclusive (test_retrieval_offline.ScopeClause) |
| W02 | retrieval | Exact-lookup regex drops superscript suffixes: article 210-1 is served as article 210 | unit-tests | test_article_suffix_is_part_of_the_number (test_retrieval_offline.ExactRoute) |
| W03 | retrieval | Exact route binds an article to the act on its left even when two acts are named | unit-tests | test_an_article_without_its_own_act_is_dropped_not_guessed (test_retrieval_offline.ExactRoute) |
| W04 | citation gate | Citation gate accepts a dovidka that also cites IDs outside the candidate set | unit-tests | test_adversarial_injection_rejected (test_generate.Gate) |
| W05 | candidates | Candidate dedup groups by article number alone, across different acts | **missed** | — |
| W06 | context budget | Context budget truncates the candidate that overflows instead of dropping it | unit-tests | test_tail_drop_whole_candidates (test_generate.Budget); test_the_list_ends_at_the_first_candidate_that_does_not_fit (test_generate.Budget) |
| W07 | data governance | USER_DATA tripwire lets non-text message parts through unscanned | unit-tests | test_uninspectable_part_never_reaches_the_client (test_user_data_tripwire.EntryPoints); test_uninspectable_part_never_reaches_the_client (test_user_data_tripwire.EntryPoints); test_uninspectable_part_never_reaches_the_client (test_user_data_tripwire.EntryPoints); test_8_non_text_content_fail_closed (test_user_data_tripwire.Tripwire) |
| W08 | api | API server binds to every network interface instead of 127.0.0.1 | lint | S104 |
| W09 | evaluation | Retrieval eval counts any article whose number merely starts with the gold number | unit-tests | test_a_longer_number_is_a_different_article (test_gold_rank.GoldRank) |
| W10 | evaluation | Harness scores an abstained answer that still lists citations as a normal answer | unit-tests | test_abstain_with_citations_not_scored_as_answered (test_harness.Taxonomy) |
| W11 | evaluation | Replay-noise gate no longer turns RED on a gold-citation flip by itself | **missed** | — |
| W12 | exit codes | fetch_cards exits 0 when card fetches failed but the editions floor is met | unit-tests | test_a_failed_card_fails_the_run_even_above_the_floor (test_rada_exit_codes.FetchCards) |
| W13 | exit codes | Unclosed amendment quote at end of file is demoted to a warning; the parse exits 0 | unit-tests | test_an_unclosed_amendment_quote_fails_the_run (test_parse_structure_main.ParseRunExitCode) |
| W14 | collection | Rada HTTP helper follows redirects by default, which disables the routing guard | unit-tests | test_raises_rada_routing_error_on_redirect (test_rada_reachability.GetNoFollow) |
| W15 | collection | Edition texts are fetched from Rada without the polite pause | unit-tests | test_a_retried_request_waits_the_polite_pause_too (test_fetch_texts.PolitePause); test_every_edition_request_waits_the_polite_pause (test_fetch_texts.PolitePause) |
| W16 | parsing | Article text no longer contains the article heading | **missed** | — |
| W17 | parsing | Duplicate unit paths are suffixed in document order: a repeal husk keeps the live path | unit-tests | test_empty_husk_yields_the_canonical_path_to_the_live_article (test_parse_structure_t9.DedupePrefersSubstantive) |
| W18 | chunking | Citations of approved documents drop their block ordinal and collide | unit-tests | test_number_is_rendered_even_for_a_lone_block (test_chunk.ApprovedBlockCitationCollision); test_two_blocks_with_the_same_title_do_not_collide (test_chunk.ApprovedBlockCitationCollision); test_approved_block_uses_its_title (test_chunk.CitationRender) |
| W19 | freshness | Freshness matcher no longer recognises the canonical nreg of the mobilisation law | unit-tests | test_builds_both_spellings (test_freshness_rada_matcher.SeedAliasMapOffline) |
| W20 | ledger | Units ledger flags only editions that shrank; growth in a known edition passes | unit-tests | test_growth_inside_a_known_edition_detected (test_units_ledger.LedgerDiff) |

## Missed

- **W05** Candidate dedup groups by article number alone, across different acts. Simplifying dedup_candidates, an agent reads the unused _act loop variable as a sign that the act half of the grouping key is dead weight and keys groups by the article stem. Same-numbered articles of different acts (the documented 78 cross-act collisions of the 'article 5' kind) now share a group: when one act's article container is present, the other act's article is subsumed and silently leaves the candidate set, even when it is the gold norm.
- **W11** Replay-noise gate no longer turns RED on a gold-citation flip by itself. Reasoning that every gold flip is also a set flip and is therefore already counted in the thresholded rate, an agent reduces the RED condition to the set-flip rate. With the 0.45 threshold, one or two gold flips among 29 questions now pass as REPLAY [GREEN] with exit 0, although the gate treats a gold flip as a hard incident at any count.
- **W16** Article text no longer contains the article heading. Seeing the heading stored both as the title and inside the text, an agent builds an article's text from its body alone. Headings such as 'Time limits for imposing an administrative penalty' disappear from chunk text and so from all three retrieval channels, and single-line articles of older editions (the whole article written on its 'Article N.' line) are stored with an empty text.

## Reproduce

```bash
uv sync
uv run python -m verification.seeded_bugs.run --catalogue verification/seeded_bugs/catalogue_v4.py --no-write
```
