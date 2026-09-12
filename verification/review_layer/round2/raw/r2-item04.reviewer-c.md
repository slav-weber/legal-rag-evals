BLOCK

```json
[{"file": "eval/retrieval_eval.py", "line": 134, "severity": "major",
  "invariant": null,
  "defect": "_gold_rank lost its match boundary: `h[\"unit_path\"] == art or h[\"unit_path\"].startswith(art + \"/\")` became a bare `startswith(art)`, so a gold article also matches any longer article number sharing its prefix (ст.21 matches ст.210 and ст.21-1).",
  "consequence": "Retrieval recall@k, precision@1 and MRR@k are silently inflated — a run that never retrieved the gold article is scored as a hit, corrupting the published numbers and the baseline the calibration rests on. As shipped the tree is also red: the pinned test fails and CI's unit-tests gate fails with it.",
  "evidence": "[LIVE]",
  "proof": "`python -m unittest tests.test_gold_rank -v` → FAIL: test_a_longer_number_is_a_different_article, 'AssertionError: 1 is not None' at tests/test_gold_rank.py:28 — _gold_rank([{act:A,unit_path:ст.210},{act:A,unit_path:ст.21-1}], [(A, ст.21)]) returns 1, expected None. Full suite: 'Ran 336 tests ... FAILED (failures=1)', and that is the only failure. verification/gates.py:38 runs exactly `unittest discover -s tests -q` as the CI unit-tests gate. The contract is documented in eval/README.md:46-48 ('частини and пункти underneath it match by prefix') and in the retrieval_eval.py:47-50 comment and test docstring ('ст.21 is not ст.210'). This hunk is unrelated to the stated refactor."},
 {"file": "eval/harness.py", "line": 529, "severity": "major",
  "invariant": null,
  "defect": "The noise gate's RED condition dropped the gold leg: `noise[\"gold_flips\"] > 0 or noise[\"set_flip_rate\"] > NOISE_FLIP_THRESHOLD` became just the rate test. The new comment ('a gold flip is a set flip too') holds per question, but the dropped leg was an any-above-zero incident test while the surviving one is a rate compared against 0.45, so a few gold flips no longer reach the threshold.",
  "consequence": "Gold-citation instability at temperature 0 — the documented HARD incident — stops failing the replay gate: up to 13 of the 29 reference questions can flip their gold citation between passes and `--mode noise` still prints REPLAY [GREEN] and exits 0, so CI and an operator see a green replay over a pipeline whose gold answers are not reproducible. No test covers this branch (the suite passes), and harness.py:535 ('RED: a gold flip (hard) OR a rate over the threshold'), harness.py:49-53, eval/README.md:177-181 and docs/ARCHITECTURE.md:112-113 all still state the old, two-level rule.",
  "evidence": "[LIVE]",
  "proof": "`--mode noise --backend stub --etalons eval/data/retrieval_gold_v0.jsonl --passes 2`, with _stub_run patched so exactly ONE of the 29 rows drops its gold citation on pass 2 and write_noise mocked (no file written): stdout 'noise [stub, 2 passes, n=29]: set-flip-rate 0.034 (thr 0.45), GOLD-flips 1 (hard incidents), 0 pass-errors → noise.jsonl. REPLAY [GREEN].' and EXIT CODE = 0. Captured measurement: gold_flips=1, set_flips=1, set_flip_rate=0.0345, thr=0.45 → NEW red expr = False, OLD red expr (gold_flips>0 or rate>thr) = True."}]
```
