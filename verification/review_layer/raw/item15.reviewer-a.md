PASS

```json
[]
```

Evidence (no suspected defect survived):
- [LIVE] I reverse-applied the 4 hunks of item15.patch in memory and ran the old and new `main()` with `open`, `_run_dir` and the clock faked, so nothing was written. Scenarios: gate on stub / stub-abstain / stub-hallucinate, score (full and `--limit 3`), noise on stub-flip / stub / stub-abstain, the default etalons, and `--no-llm`. Old and new gave the same exit codes (0,1,1,0,0,1,0,0,1,0), the same stdout, the same artifact names and bytes, and the same `open()` arguments (`"w"`, `encoding="utf-8"`). Direct `write_run` calls (with and without golden, empty detail, non-ASCII rows) and direct `write_noise` calls were also byte-identical.
- [LIVE] `python -m ruff check --no-cache eval/harness.py`: all checks passed.
- [CODE] The run-id stamp is unchanged (`%Y-%m-%dT%H%M%S` UTC + `_<backend>`, as eval/README.md documents). `NOISE_FLIP_THRESHOLD`, the gold and golden files and the tests are untouched (invariants 5 and 7 hold). `write_run` and `write_noise` keep their signatures, and nothing outside eval/harness.py and tests/test_harness.py calls them.
- One behavioural difference, not reachable from any caller: with no `"detail"` key in `res`/`noise`, the new code raises `KeyError` before opening the file, where the old code left a file holding only the header. `score()` and `measure_noise()` always return `"detail"`.
