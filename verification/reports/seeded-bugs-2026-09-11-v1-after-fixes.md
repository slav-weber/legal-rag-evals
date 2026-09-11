# Seeded-bug benchmark · 2026-09-11 · v1-after-fixes

**The deterministic gates caught 26 of 26 planted bugs (100 %).** The canary (B00) was caught by unit-tests, test-ratchet.

| | |
|---|---|
| Measured | 2026-09-11T12:50:05Z · git `6ce4ca0` · Windows · Python 3.12.13 |
| Tree | sha256 `1bf286d22b85db225027a3a5da31f00da9ee44f7636968d0f2b388fa488b10f8` over 127 files |
| Catalogue | `verification/seeded_bugs/catalogue.py` · sha256 `528d6f74aa8fc49149c63c7fadf011dc7e5da4ea10b608b9ea886b901eb1f37e` |
| Gates | unit-tests · test-ratchet · lint · eval-no-llm · eval-stub-gate (the list CI runs: `verification/gates.py`) |

## By area

| Area | Planted | Caught |
|---|---|---|
| api | 2 | 2 |
| citation gate | 3 | 3 |
| context budget | 2 | 2 |
| data governance | 2 | 2 |
| evaluation | 3 | 3 |
| exit codes | 3 | 3 |
| rendering | 3 | 3 |
| retrieval | 7 | 7 |
| test integrity | 1 | 1 |

## Every bug

| Bug | Area | Planted defect | Caught by | Evidence |
|---|---|---|---|---|
| B01 | citation gate | The gate accepts citation IDs outside the candidate set | unit-tests | test_adversarial_injection_rejected (test_generate.Gate); test_out_of_set_retries_then_abstains (test_generate.Gate); test_recovers_on_retry (test_generate.Gate); test_retry_appends_assistant_tool_call_turn (test_generate.Gate); test_in_set_resolves_out_of_set_is_invalid (test_generate.Resolve) |
| B02 | citation gate | One regeneration fewer before the honest abstain | unit-tests | test_out_of_set_retries_then_abstains (test_generate.Gate); test_zero_citation_slip_rejected (test_generate.Gate) |
| B03 | citation gate | An answer without citations passes when it has a conclusion | unit-tests | test_zero_citation_slip_rejected (test_generate.Gate) |
| B04 | context budget | The budget can drop every candidate | unit-tests | test_keeps_at_least_one_never_truncates (test_generate.Budget) |
| B05 | context budget | A candidate that fits the budget exactly is dropped | unit-tests | test_candidate_that_fits_exactly_is_kept (test_generate.Budget) |
| B06 | rendering | Citation chips are rendered without HTML escaping | unit-tests | test_escapes_markup_inside_a_citation_chip (test_generate.Render) |
| B07 | rendering | Internal candidate IDs reach the reader's text | unit-tests | test_strips_leaked_internal_cids (test_generate.Render) |
| B08 | rendering | An abstain shows the model's own prose | unit-tests | test_abstain_renders_fixed_copy_and_zero_model_prose (test_generate.Render) |
| B09 | retrieval | An edition whose last day in force is today is filtered out | unit-tests | test_both_bounds_are_inclusive (test_retrieval_offline.ScopeClause) |
| B10 | retrieval | RRF fusion ignores the calibrated channel weights | unit-tests | test_weights_decide_the_order (test_retrieval_offline.Fusion) |
| B11 | retrieval | A failed retrieval channel disappears without a degradation flag | unit-tests | test_failed_channel_is_flagged_and_the_survivors_fuse (test_retrieval_offline.Degradation) |
| B12 | retrieval | Code abbreviations match case-insensitively | unit-tests | test_code_abbreviations_are_case_sensitive (test_retrieval_offline.ExactRoute) |
| B13 | retrieval | The reranker fallback is not flagged as degraded | unit-tests | test_reranker_outage_is_flagged_not_passed_off_as_reranked (test_retrieval_offline.Degradation) |
| B14 | retrieval | The Ukrainian apostrophe U+02BC is not normalised | unit-tests | test_apostrophe_variants_fold_to_one (test_retrieval_offline.Normalisation) |
| B15 | retrieval | «стаття 210-1» is parsed as article 210 | unit-tests | test_article_suffix_is_part_of_the_number (test_retrieval_offline.ExactRoute) |
| B16 | data governance | The user-data tripwire no longer scans dictionary keys | unit-tests | test_D_sentinel_in_dict_key (test_user_data_tripwire.Tripwire); test_safe_scalars_skipped (test_user_data_tripwire.WalkStrings); test_scans_keys_and_values (test_user_data_tripwire.WalkStrings) |
| B17 | data governance | The tripwire lets through values it cannot inspect | unit-tests | test_B_bytes_value_rejected (test_user_data_tripwire.Tripwire); test_C_set_value_rejected (test_user_data_tripwire.Tripwire); test_G_object_with_sentinel_str_rejected (test_user_data_tripwire.Tripwire); test_uninspectable_raises (test_user_data_tripwire.WalkStrings) |
| B18 | exit codes | The worst of several exit codes is taken as the numeric maximum | unit-tests | test_worst_severity_not_bitwise (test_exitcodes.Convention) |
| B19 | exit codes | A run that collected less than expected exits 0 | unit-tests | test_fail_if (test_exitcodes.Convention) |
| B20 | exit codes | The snapshot run exits 0 on network errors | unit-tests | test_errors_fail (test_exitcodes.KsuExit); test_errors_win_over_defer (test_exitcodes.KsuExit); test_errors_are_nonzero (test_ksu_snapshot_exit.ExitCodeUnit); test_http_500_exits_nonzero (test_ksu_snapshot_exit.MainFailurePathSmoke); test_network_exception_exits_nonzero (test_ksu_snapshot_exit.MainFailurePathSmoke) |
| B21 | api | A 500 response carries the exception text | unit-tests | test_500_internal_error_clean_body (test_api.ApiSeam) |
| B22 | api | The dev server listens on every network interface | lint | S104 |
| B23 | evaluation | Gold matching by string prefix: ст.21 also matches ст.210 | unit-tests | test_a_longer_number_is_a_different_article (test_gold_rank.GoldRank) |
| B24 | evaluation | An abstain that still cites something is scored as an answer | unit-tests | test_abstain_with_citations_not_scored_as_answered (test_harness.Taxonomy) |
| B25 | evaluation | The harness gate passes despite hallucinated citations | unit-tests | test_hallucination_alone_turns_the_gate_red (test_harness.CliGate) |
| B26 | test integrity | B01, with the five tests that caught it marked as skipped | test-ratchet | RATCHET: 5 skip(s) not on the allowed list: test_generate.Gate.test_adversarial_injection_rejected, test_generate.Gate.test_out_of_set_retries_then_abstains, test_generate.Gate.test_recovers_on_retry, test_generate.Gate.test_retry_appends_assistant_tool_call_turn, test_generate.Resolve.test_in_set_resolves_out_of_set_is_invalid. Removing or skipping tests needs a deliberate --update in the same commit, where a reviewer can see it. |

## Reproduce

```bash
uv sync
uv run python -m verification.seeded_bugs.run --no-write
```
