PASS
[]

Notes (observed at runtime in the tree; the harness ran in-process with write_run and write_noise patched out, so no file was written):
- `--mode gate --backend stub-hallucinate` over the 29 gold rows exits 1 with hallucination=29 and an empty golden-mechanical-RED list; `stub` still exits 0 and `stub-abstain` still exits 1. The new stub isolates the hallucination branch of the gate RED condition, as described.
- Without the change, argparse rejects `stub-hallucinate` with exit 2. So the committed test `test_harness.CliGate.test_hallucination_alone_turns_the_gate_red`, already recorded in `verification/test_inventory.json`, fails before the change and passes after it.
- An in-memory mutant that drops the hallucination term from the gate RED condition still gives exit 0 for `stub` and 1 for `stub-abstain`, so the older CLI test cannot see it; `stub-hallucinate` then exits 0, so the new test catches it.
- ruff on `eval/harness.py`: all checks passed. The 22 harness unit tests that write no files pass. No gold file, golden case, threshold, default, test or gate was changed.
