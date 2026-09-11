# Seeded-bug benchmark · 2026-09-11

**The deterministic gates caught 13 of 26 planted bugs (50 %).** The canary (B00) was caught by unit-tests.

| | |
|---|---|
| Measured | 2026-09-11T12:23:21Z · git `23ae162` · Windows · Python 3.12.13 |
| Tree | sha256 `b60e2b8c413c1f553637917229f9b31242d81317688cabdc37449b927a8eed38` over 121 files |
| Catalogue | `verification/seeded_bugs/catalogue.py` · sha256 `528d6f74aa8fc49149c63c7fadf011dc7e5da4ea10b608b9ea886b901eb1f37e` |
| Gates | unit-tests · lint · eval-no-llm · eval-stub-gate (the list CI runs: `verification/gates.py`) |

## By area

| Area | Planted | Caught |
|---|---|---|
| api | 2 | 1 |
| citation gate | 3 | 3 |
| context budget | 2 | 1 |
| data governance | 2 | 2 |
| evaluation | 3 | 1 |
| exit codes | 3 | 3 |
| rendering | 3 | 2 |
| retrieval | 7 | 0 |
| test integrity | 1 | 0 |

## Every bug

| Bug | Area | Planted defect | Caught by | Evidence |
|---|---|---|---|---|
| B01 | citation gate | The gate accepts citation IDs outside the candidate set | unit-tests | test_adversarial_injection_rejected (test_generate.Gate); test_out_of_set_retries_then_abstains (test_generate.Gate); test_recovers_on_retry (test_generate.Gate); test_retry_appends_assistant_tool_call_turn (test_generate.Gate); test_in_set_resolves_out_of_set_is_invalid (test_generate.Resolve) |
| B02 | citation gate | One regeneration fewer before the honest abstain | unit-tests | test_out_of_set_retries_then_abstains (test_generate.Gate); test_zero_citation_slip_rejected (test_generate.Gate) |
| B03 | citation gate | An answer without citations passes when it has a conclusion | unit-tests | test_zero_citation_slip_rejected (test_generate.Gate) |
| B04 | context budget | The budget can drop every candidate | unit-tests | test_keeps_at_least_one_never_truncates (test_generate.Budget) |
| B05 | context budget | A candidate that fits the budget exactly is dropped | **missed** | — |
| B06 | rendering | Citation chips are rendered without HTML escaping | **missed** | — |
| B07 | rendering | Internal candidate IDs reach the reader's text | unit-tests | test_strips_leaked_internal_cids (test_generate.Render) |
| B08 | rendering | An abstain shows the model's own prose | unit-tests | test_abstain_renders_fixed_copy_and_zero_model_prose (test_generate.Render) |
| B09 | retrieval | An edition whose last day in force is today is filtered out | **missed** | — |
| B10 | retrieval | RRF fusion ignores the calibrated channel weights | **missed** | — |
| B11 | retrieval | A failed retrieval channel disappears without a degradation flag | **missed** | — |
| B12 | retrieval | Code abbreviations match case-insensitively | **missed** | — |
| B13 | retrieval | The reranker fallback is not flagged as degraded | **missed** | — |
| B14 | retrieval | The Ukrainian apostrophe U+02BC is not normalised | **missed** | — |
| B15 | retrieval | «стаття 210-1» is parsed as article 210 | **missed** | — |
| B16 | data governance | The user-data tripwire no longer scans dictionary keys | unit-tests | test_D_sentinel_in_dict_key (test_user_data_tripwire.Tripwire); test_safe_scalars_skipped (test_user_data_tripwire.WalkStrings); test_scans_keys_and_values (test_user_data_tripwire.WalkStrings) |
| B17 | data governance | The tripwire lets through values it cannot inspect | unit-tests | test_B_bytes_value_rejected (test_user_data_tripwire.Tripwire); test_C_set_value_rejected (test_user_data_tripwire.Tripwire); test_G_object_with_sentinel_str_rejected (test_user_data_tripwire.Tripwire); test_uninspectable_raises (test_user_data_tripwire.WalkStrings) |
| B18 | exit codes | The worst of several exit codes is taken as the numeric maximum | unit-tests | test_worst_severity_not_bitwise (test_exitcodes.Convention) |
| B19 | exit codes | A run that collected less than expected exits 0 | unit-tests | test_fail_if (test_exitcodes.Convention) |
| B20 | exit codes | The snapshot run exits 0 on network errors | unit-tests | test_errors_fail (test_exitcodes.KsuExit); test_errors_win_over_defer (test_exitcodes.KsuExit); test_errors_are_nonzero (test_ksu_snapshot_exit.ExitCodeUnit); test_http_500_exits_nonzero (test_ksu_snapshot_exit.MainFailurePathSmoke); test_network_exception_exits_nonzero (test_ksu_snapshot_exit.MainFailurePathSmoke) |
| B21 | api | A 500 response carries the exception text | unit-tests | test_500_internal_error_clean_body (test_api.ApiSeam) |
| B22 | api | The dev server listens on every network interface | **missed** | — |
| B23 | evaluation | Gold matching by string prefix: ст.21 also matches ст.210 | **missed** | — |
| B24 | evaluation | An abstain that still cites something is scored as an answer | unit-tests | test_abstain_with_citations_not_scored_as_answered (test_harness.Taxonomy) |
| B25 | evaluation | The harness gate passes despite hallucinated citations | **missed** | — |
| B26 | test integrity | B01, with the five tests that caught it marked as skipped | **missed** | — |

## Missed

- **B05** A candidate that fits the budget exactly is dropped. Tightens the budget check to strictly below the limit.
- **B06** Citation chips are rendered without HTML escaping. Removes what looks like double escaping around the citation chip.
- **B09** An edition whose last day in force is today is filtered out. Rewrites the in-force check with a strict comparison.
- **B10** RRF fusion ignores the calibrated channel weights. Calls the weighting premature and gives every channel the same weight.
- **B11** A failed retrieval channel disappears without a degradation flag. Treats a failed channel as noise; the fused result looks whole although a channel is lost.
- **B12** Code abbreviations match case-insensitively. Makes the abbreviation match case-insensitive for robustness; the word «кас» (a cash desk) now routes a question to the Code of Administrative Procedure.
- **B13** The reranker fallback is not flagged as degraded. Removes the degradation flag in the reranker fallback because the RRF order is good enough.
- **B14** The Ukrainian apostrophe U+02BC is not normalised. Normalises apostrophe variants but forgets the modifier letter apostrophe Ukrainian uses.
- **B15** «стаття 210-1» is parsed as article 210. Simplifies the article-number pattern to digits only.
- **B22** The dev server listens on every network interface. Binds to 0.0.0.0 to reach the dev server from another machine.
- **B23** Gold matching by string prefix: ст.21 also matches ст.210. Simplifies the article match to a prefix test.
- **B25** The harness gate passes despite hallucinated citations. Removes the hallucination condition because the stub cannot hallucinate anyway.
- **B26** B01, with the five tests that caught it marked as skipped. Faced with five red tests after the B01 change, the agent skips them as superseded by the new resolver, and the suite is green again.

## Reproduce

```bash
uv sync
uv run python -m verification.seeded_bugs.run
```
