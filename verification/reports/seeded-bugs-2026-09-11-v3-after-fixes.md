# Seeded-bug benchmark · 2026-09-11 · v3-after-fixes

**The deterministic gates caught 20 of 20 planted bugs (100 %).** The canary (V00) was caught by unit-tests, test-ratchet, eval-no-llm, eval-stub-gate.

| | |
|---|---|
| Measured | 2026-09-11T20:14:13Z · git `b2bf4b7` · Windows · Python 3.12.13 |
| Tree | sha256 `227acaac0d90639bd0b5a44c2cad1e50ddec895ffd1331e4aeec506768836f42` over 236 files |
| Catalogue | `verification/seeded_bugs/catalogue_v3.py` · sha256 `e379497950e59c2c98d502139f5f85576c00b961c7f117656951d9ccba70e924` |
| Gates | unit-tests · test-ratchet · lint · eval-no-llm · eval-stub-gate (the list CI runs: `verification/gates.py`) |

## By area

| Area | Planted | Caught |
|---|---|---|
| api | 2 | 2 |
| chunking | 1 | 1 |
| citation gate | 2 | 2 |
| collection | 1 | 1 |
| context budget | 1 | 1 |
| data governance | 1 | 1 |
| evaluation | 2 | 2 |
| exit codes | 2 | 2 |
| freshness | 2 | 2 |
| ledger | 1 | 1 |
| parsing | 2 | 2 |
| retrieval | 3 | 3 |

## Every bug

| Bug | Area | Planted defect | Caught by | Evidence |
|---|---|---|---|---|
| V01 | retrieval | Candidate channels ignore the as_of date and gate on today | unit-tests | test_hybrid_gates_every_channel_on_the_requested_date (test_retrieval_offline.AsOfReachesEveryChannel); test_search_gates_every_route_on_the_requested_date (test_retrieval_offline.AsOfReachesEveryChannel) |
| V02 | retrieval | RRF fusion returns the lowest-scoring candidates first | unit-tests | test_weights_decide_the_order (test_retrieval_offline.Fusion) |
| V03 | retrieval | Code abbreviations match case-insensitively on the raw question | unit-tests | test_code_abbreviations_are_case_sensitive (test_retrieval_offline.ExactRoute) |
| V04 | citation gate | Out-of-set citation IDs pass when one other ID resolves | unit-tests | test_adversarial_injection_rejected (test_generate.Gate) |
| V05 | citation gate | A dovidka without legal theses is accepted with no citation | unit-tests | test_answer_without_theses_is_regenerated_then_abstains (test_generate.Gate); test_answer_without_theses_is_regenerated_then_abstains (test_generate.Gate) |
| V06 | context budget | The last candidate is truncated to fill the context budget | unit-tests | test_tail_drop_whole_candidates (test_generate.Budget); test_the_list_ends_at_the_first_candidate_that_does_not_fit (test_generate.Budget) |
| V07 | data governance | The USER_DATA tripwire is logged and skipped on generation | unit-tests | test_marked_user_data_never_reaches_the_client (test_user_data_tripwire.EntryPoints); test_marked_user_data_never_reaches_the_client (test_user_data_tripwire.EntryPoints); test_uninspectable_part_never_reaches_the_client (test_user_data_tripwire.EntryPoints); test_uninspectable_part_never_reaches_the_client (test_user_data_tripwire.EntryPoints); test_user_data_flag_never_reaches_the_client (test_user_data_tripwire.EntryPoints); test_user_data_flag_never_reaches_the_client (test_user_data_tripwire.EntryPoints) |
| V08 | api | A generation-provider outage is answered as a 200 abstain | unit-tests | test_provider_failure_inside_generate_is_500_not_an_abstain (test_api.RealGeneratePath); test_provider_outage_inside_generate_is_503_not_an_abstain (test_api.RealGeneratePath); test_provider_error_during_a_regeneration_propagates (test_generate.Gate); test_provider_error_propagates_instead_of_abstaining (test_generate.Gate); test_provider_error_propagates_instead_of_abstaining (test_generate.Gate) |
| V09 | api | The API seam binds to every network interface | lint | S104 |
| V10 | evaluation | Retrieval eval counts neighbouring article numbers as gold hits | unit-tests | test_a_longer_number_is_a_different_article (test_gold_rank.GoldRank) |
| V11 | evaluation | Golden cases that raise are skipped and the gate stays green | unit-tests | test_gate_is_not_green_when_the_golden_calls_raise (test_harness.GoldenCallRaises); test_run_golden_does_not_skip_a_case_whose_call_raises (test_harness.GoldenCallRaises) |
| V12 | exit codes | worst() takes the numeric maximum, so FAIL plus SKIP reads SKIP | unit-tests | test_worst_severity_not_bitwise (test_exitcodes.Convention) |
| V13 | exit codes | An unclosed amendment quote no longer fails the parse run | unit-tests | test_an_unclosed_amendment_quote_fails_the_run (test_parse_structure_main.ParseRunExitCode) |
| V14 | collection | fetch_texts skips the polite pause between Rada requests | unit-tests | test_a_retried_request_waits_the_polite_pause_too (test_fetch_texts.PolitePause); test_every_edition_request_waits_the_polite_pause (test_fetch_texts.PolitePause) |
| V15 | freshness | The probe's previous signal can be a failed probe's NULL | unit-tests | test_a_failed_probe_null_is_not_the_previous_signal (test_freshness_last_signal.LastSignal); test_the_latest_successful_signal_of_this_source_wins (test_freshness_last_signal.LastSignal) |
| V16 | freshness | A budget-truncated backstop run writes a signal over a subset | unit-tests | test_partial_run_signal_none_no_change (test_rada_backstop.RunSignal) |
| V17 | parsing | Duplicate unit paths go to document order and the repealed husk wins | unit-tests | test_empty_husk_yields_the_canonical_path_to_the_live_article (test_parse_structure_t9.DedupePrefersSubstantive) |
| V18 | parsing | The amendment-marker pattern turns greedy and deletes legal text | unit-tests | test_both_notes_become_markers (test_parse_structure_t9.AmendmentNotes); test_both_notes_become_markers (test_parse_structure_t9.AmendmentNotes); test_text_between_two_notes_is_kept (test_parse_structure_t9.AmendmentNotes); test_text_between_two_notes_is_kept (test_parse_structure_t9.AmendmentNotes) |
| V19 | ledger | The units ledger no longer flags units injected into an edition | unit-tests | test_growth_inside_a_known_edition_detected (test_units_ledger.LedgerDiff) |
| V20 | chunking | Approved-document citations drop the block ordinal | unit-tests | test_number_is_rendered_even_for_a_lone_block (test_chunk.ApprovedBlockCitationCollision); test_two_blocks_with_the_same_title_do_not_collide (test_chunk.ApprovedBlockCitationCollision); test_approved_block_uses_its_title (test_chunk.CitationRender) |

## Reproduce

```bash
uv sync
uv run python -m verification.seeded_bugs.run --catalogue verification/seeded_bugs/catalogue_v3.py --no-write
```
