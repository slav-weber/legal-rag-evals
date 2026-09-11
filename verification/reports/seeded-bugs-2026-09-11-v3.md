# Seeded-bug benchmark · 2026-09-11 · v3

**The deterministic gates caught 10 of 20 planted bugs (50 %).** The canary (V00) was caught by unit-tests, test-ratchet, eval-no-llm, eval-stub-gate.

| | |
|---|---|
| Measured | 2026-09-11T14:34:20Z · git `32dff05` · Windows · Python 3.12.13 |
| Tree | sha256 `b912f82eaa4720399e712fee99d5d63193794992e7e1a2b1e784f50d3cee25f2` over 138 files |
| Catalogue | `verification/seeded_bugs/catalogue_v3.py` · sha256 `e379497950e59c2c98d502139f5f85576c00b961c7f117656951d9ccba70e924` |
| Gates | unit-tests · test-ratchet · lint · eval-no-llm · eval-stub-gate (the list CI runs: `verification/gates.py`) |

## By area

| Area | Planted | Caught |
|---|---|---|
| api | 2 | 1 |
| chunking | 1 | 1 |
| citation gate | 2 | 1 |
| collection | 1 | 0 |
| context budget | 1 | 1 |
| data governance | 1 | 0 |
| evaluation | 2 | 1 |
| exit codes | 2 | 1 |
| freshness | 2 | 1 |
| ledger | 1 | 0 |
| parsing | 2 | 1 |
| retrieval | 3 | 2 |

## Every bug

| Bug | Area | Planted defect | Caught by | Evidence |
|---|---|---|---|---|
| V01 | retrieval | Candidate channels ignore the as_of date and gate on today | **missed** | — |
| V02 | retrieval | RRF fusion returns the lowest-scoring candidates first | unit-tests | test_weights_decide_the_order (test_retrieval_offline.Fusion) |
| V03 | retrieval | Code abbreviations match case-insensitively on the raw question | unit-tests | test_code_abbreviations_are_case_sensitive (test_retrieval_offline.ExactRoute) |
| V04 | citation gate | Out-of-set citation IDs pass when one other ID resolves | unit-tests | test_adversarial_injection_rejected (test_generate.Gate) |
| V05 | citation gate | A dovidka without legal theses is accepted with no citation | **missed** | — |
| V06 | context budget | The last candidate is truncated to fill the context budget | unit-tests | test_tail_drop_whole_candidates (test_generate.Budget); test_the_list_ends_at_the_first_candidate_that_does_not_fit (test_generate.Budget) |
| V07 | data governance | The USER_DATA tripwire is logged and skipped on generation | **missed** | — |
| V08 | api | A generation-provider outage is answered as a 200 abstain | **missed** | — |
| V09 | api | The API seam binds to every network interface | lint | S104 |
| V10 | evaluation | Retrieval eval counts neighbouring article numbers as gold hits | unit-tests | test_a_longer_number_is_a_different_article (test_gold_rank.GoldRank) |
| V11 | evaluation | Golden cases that raise are skipped and the gate stays green | **missed** | — |
| V12 | exit codes | worst() takes the numeric maximum, so FAIL plus SKIP reads SKIP | unit-tests | test_worst_severity_not_bitwise (test_exitcodes.Convention) |
| V13 | exit codes | An unclosed amendment quote no longer fails the parse run | **missed** | — |
| V14 | collection | fetch_texts skips the polite pause between Rada requests | **missed** | — |
| V15 | freshness | The probe's previous signal can be a failed probe's NULL | **missed** | — |
| V16 | freshness | A budget-truncated backstop run writes a signal over a subset | unit-tests | test_partial_run_signal_none_no_change (test_rada_backstop.RunSignal) |
| V17 | parsing | Duplicate unit paths go to document order and the repealed husk wins | unit-tests | test_empty_husk_yields_the_canonical_path_to_the_live_article (test_parse_structure_t9.DedupePrefersSubstantive) |
| V18 | parsing | The amendment-marker pattern turns greedy and deletes legal text | **missed** | — |
| V19 | ledger | The units ledger no longer flags units injected into an edition | **missed** | — |
| V20 | chunking | Approved-document citations drop the block ordinal | unit-tests | test_number_is_rendered_even_for_a_lone_block (test_chunk.ApprovedBlockCitationCollision); test_two_blocks_with_the_same_title_do_not_collide (test_chunk.ApprovedBlockCitationCollision); test_approved_block_uses_its_title (test_chunk.CitationRender) |

## Missed

- **V01** Candidate channels ignore the as_of date and gate on today. Tidying the channel dispatch in _run_channel into keyword style, an agent passes only k=topn and drops the positional as_of, which dense(), fts() and lemma() default to None. Every channel candidate is then scope-gated on today's Kyiv date instead of the date the caller asked about, so a question with as_of set (the API accepts one) is answered from the editions in force today; only the exact route still honours the date.
- **V05** A dovidka without legal theses is accepted with no citation. A purely practical answer (a conclusion and steps, no theses) was regenerated twice and then abstained, so an agent limits the mandatory-citation rule to dovidkas that carry theses. The model can now dodge the gate by leaving obgruntuvannya empty: a conclusion and action steps about the law, drawn from its own memory and backed by no candidate, are returned as a valid, non-abstained answer.
- **V07** The USER_DATA tripwire is logged and skipped on generation. A regeneration turn crashed on a message part the fail-closed walker could not inspect, so an agent wraps the guard in call_tool_deepseek to log the ValueError and carry on. The USER_DATA tripwire raises the same ValueError, so a prompt carrying the user-data sentinel is now logged and sent anyway to an external model with no zero-data retention: the seatbelt no longer holds on the generation path.
- **V08** A generation-provider outage is answered as a 200 abstain. To stop one transient DeepSeek timeout from failing the whole request, an agent catches provider errors in the generation loop and lets it fall through to the abstain. An outage, a missing API key or a truncated tool call now comes back as HTTP 200 with the fixed 'no grounds in the available norms' copy instead of 503 generation_unavailable: users are told the law gives no answer, monitoring sees no errors, and a live harness run scores the outage as abstains rather than errors.
- **V11** Golden cases that raise are skipped and the gate stays green. Mirroring score()'s per-row catch, an agent wraps the golden calls in _run_safe and skips a case whose call raised. When the live pipeline is down every reference question lands in errors and every golden case is skipped, so --mode gate prints GREEN and exits 0 on a run that scored nothing; a regression that makes generate() raise on a golden question is equally invisible.
- **V13** An unclosed amendment quote no longer fails the parse run. The orchestrated daily parse kept going red on one old edition, so an agent demotes the unclosed-quote check to a warning: the message is still printed, but the run falls through to the normal summary (failed=0) and exit 0. Editions whose structural tail was suppressed and merged into one unit are written and journaled as fully parsed, and the only honest signal that their units are untrustworthy is gone.
- **V14** fetch_texts skips the polite pause between Rada requests. Backfilling 121 editions of the Code of Administrative Offences took hours because of the 6-second polite pause, and an agent reasons that the daily byte budget already meters Rada, so it passes polite=False. The budget caps bytes, not request rate: edition downloads now go out back to back, far above the host's published per-minute terms, which is exactly the traffic that earns the collector's IP a multi-hour anti-DDoS block.
- **V15** The probe's previous signal can be a failed probe's NULL. Simplifying _last_signal to 'the latest row for this source', an agent drops the signal_value IS NOT NULL filter. After any failed probe (a Rada 403 writes a NULL signal) the next real signal is compared against NULL, changed stays False and the new baseline silently absorbs the move: a new edition of a seed act that lands around a failed probe never turns the source yellow, and the corpus keeps serving the superseded edition as current law.
- **V18** The amendment-marker pattern turns greedy and deletes legal text. A marker nested inside another marker left a stray fragment and brace in the clean text, so an agent widens MARKER_RE from a brace-free body to .* (the pattern already has DOTALL). The match is now greedy across lines: _clean deletes everything from a unit's first amendment note to its last, so an article amended twice silently loses all the legal text between the two notes, which is stored as one giant marker instead.
- **V19** The units ledger no longer flags units injected into an edition. After a reparse that legitimately added units to a known edition turned the data gate red, an agent narrows the ledger diff to shrinkage only. An injection into a known edition, such as a reparse that turns quoted amendment headings into phantom host articles, now passes silently while the totals stay above their floors, which is half of what the ledger exists to catch.

## Reproduce

```bash
uv sync
uv run python -m verification.seeded_bugs.run --catalogue verification/seeded_bugs/catalogue_v3.py --no-write
```
