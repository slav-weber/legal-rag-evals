BLOCK

```json
[{"file": "api/main.py", "line": 164, "severity": "critical",
  "invariant": null,
  "defect": "main() binds the API to 0.0.0.0 instead of 127.0.0.1, an edit unrelated to the described retrieval/generate refactor, while the comment on the same line still reads `# localhost ONLY (dev)`.",
  "consequence": "The seam that by design has no auth, no rate limit and no user-data protection becomes reachable from the whole LAN instead of the loopback: anyone on the network can drive generation, burn the DeepSeek budget and cause questions to be persisted into traces/t14.",
  "evidence": "[LIVE]",
  "proof": "Ran `python -m verification.gates` in the tree: `FAIL (exit 1)  lint` with `api\\main.py:164:27: S104 Possible binding to all interfaces` (final line: `RED: 3/5 gate(s) passed; failed: unit-tests, lint`). The bind is pinned as a red line in three places the diff leaves untouched: api/main.py:5 'the server binds 127.0.0.1 ONLY', README.md:24 'bound to 127.0.0.1', docs/ARCHITECTURE.md:91 'bound to 127.0.0.1 only'. No test covers the host (grep host|uvicorn|main\\( in tests/test_api.py returns only an unrelated localhost URL at line 155), so lint is the only thing standing between this and a merge."},

 {"file": "pipelines/rag/retrieval.py", "line": 310, "severity": "critical",
  "invariant": null,
  "defect": "_ART_RE lost its `(?:-\\d+)?` suffix group, so a hyphenated article number is truncated to its first digit run and «ст.210-1» parses as «ст.210».",
  "consequence": "The deterministic citation route — the one whose whole contract is 'a citation is an ID, never a relevance guess', and which stays SILENT rather than guess — now resolves a cited ст.N-M to a DIFFERENT article and serves that article's leaves as the authoritative #1 candidates. A user asking about ст.210-1 КУпАП (the military-registration fine; eval/data/smoke_retrieval.jsonl id 2 pins expected_article 'ст.210-1') is answered from ст.210.",
  "evidence": "[LIVE]",
  "proof": "`python -m unittest discover -s tests -q` → `FAILED (failures=1)`: test_retrieval_offline.ExactRoute.test_article_suffix_is_part_of_the_number, `AssertionError: 'ст.210' != 'ст.210-1'` (tests/test_retrieval_offline.py:144-145 also pins 'ст. 173-2' → 'ст.173-2'). End-to-end through the real route: with _TITLE_KEYS_CACHE patched to [], `R._citations(None, 'Яка санкція за ст. 210-1 КУпАП?')` → `[('8073-10', 'ст.210')]` and `R._parse_article(...)` → `'ст.210'`; exact_lookup then queries unit_path = 'ст.210' OR 'ст.210/%'. The comment directly above the line still documents the dropped case («ст.N-M»), retrieval.py:100 still discusses «283-2», and generate.py:40 `_ARTNUM_RE` still carries `(\\d+(?:-\\d+)?)`, so retrieval and the prose lint now disagree on what an article number is."},

 {"file": "pipelines/rag/generate.py", "line": 117, "severity": "major",
  "invariant": null,
  "defect": "dedup_candidates now groups by the article stem alone — the `act` was dropped from the grouping key — so the same article number retrieved from two different acts lands in one group and the container-subsume branch keeps only the highest-ranked member, discarding the other act's candidate.",
  "consequence": "A correctly retrieved, in-force norm from a second act never reaches the closed C1..Ck set, so the model cannot cite it and the довідка is grounded on one act only; on a query that explicitly cites both (e.g. «ст.5 КАС і ст.5 КУпАП») one of the two named articles just disappears. The drop is silent — `dropped` reports only empty_text and budget — which build_candidates' own docstring calls 'our antipattern', and the module docstring (generate.py:11-12) names the cross-act «ст.5» collision as the very hazard this layer exists to handle.",
  "evidence": "[LIVE]",
  "proof": "Ran dedup_candidates against an inlined copy of the pre-change grouping (ASCII stand-ins for the unit paths to keep console encoding out of it):\n  containers, two acts  OLD: [('8073-10', 'st.5'), ('2747-15', 'st.5')]\n  containers, two acts  NEW: [('8073-10', 'st.5')]\n  container A + leaves B OLD: [('8073-10', 'st.5'), ('2747-15', 'st.5/p.1'), ('2747-15', 'st.5/p.2')]\n  container A + leaves B NEW: [('8073-10', 'st.5')]\nIn the second case one act's container swallows another act's two leaves. The function's own docstring at generate.py:110 still says 'Per (act, article-stem) group', so code and contract now contradict each other. No test catches it: tests/test_generate.py:260-278 builds every fixture with act 'A', and verification/README.md:298 already catalogues this exact defect as missed weakness W05 — 'the fixtures vary the unit path and never the act, so a key that ignores the act changes nothing they can see'."}]
```
