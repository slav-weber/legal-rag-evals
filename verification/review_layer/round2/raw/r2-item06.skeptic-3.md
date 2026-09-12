CONFIRMED

[LIVE] Feeding `build_candidates` the four hits `exact_lookup` returns for «ст.5 КАС і ст.5 КУпАП» (a container plus a leaf from each act) yields the candidate set `[('C1', '2747-15', 'st.5')]` — the second act is gone — and `dropped` comes back `{'empty_text': [], 'budget': [], 'n_before': 1, 'n_kept': 1}`, so the loss is silent and lands before the report can even count it.

[CODE] The input is reachable and expected rather than hypothetical: `_citations` (retrieval.py:391-419) documents «ст.47 КАС і ст.210 КУпАП» → both pairs, `exact_lookup` round-robins the two acts into one list, and generate.py:11-12 names the 78 cross-act «ст.5» collisions as the hazard this layer exists for; nothing downstream restores the discarded member, and `dedup_candidates`' own docstring (generate.py:110) still promises "Per (act, article-stem) group", so code and contract now contradict each other.

[LIVE] No test objects — `tests.test_generate` runs 43/43 OK with the defect in place, because every `Dedup` fixture uses act "A" (test_generate.py:260-278), exactly the blindness verification/README.md:298 already catalogues as missed weakness W05.
