CONFIRMED

[LIVE] Driving the repo's own harness over one CLOSED + one UNCLOSED edition gives `exit code: 0` with `COLLECT-SUMMARY parsed: {'ok': 2, 'failed': 0, ...}` while 12 units from the truncated edition still go through `_write`; `-m unittest discover -s tests -q` fails `ParseRunExitCode.test_an_unclosed_amendment_quote_fails_the_run` with `AssertionError: 0 != 1`, and `-m verification.gates` reports `RED: 4/5 gate(s) passed; failed: unit-tests`.

[CODE] No escape exists: `quote_eof_bad` and `_quote_eof_warn` are consumed only inside `main()`, nothing else under `pipelines/` reads the `!!`/`UNCLOSED` line, and `summary.parse` falls back to `items_failed=1` only when the line is MISSING — here it is present and says `failed=0`, so the orchestrator journals a clean run and the operator gets no signal on any channel.

[CODE] The added `# warning only: one bad edition must not block the nightly chain` appears nowhere else in the repo and contradicts the retained comment two lines above ("the only honest signal is a failed run"), the test module's docstring, `pipelines/exitcodes.py` and AGENTS.md invariant 5; the test is a pinned entry in `verification/test_inventory.json`, so the behaviour cannot be legitimised by deleting it, and the author's description covers only the freshness refactor.
