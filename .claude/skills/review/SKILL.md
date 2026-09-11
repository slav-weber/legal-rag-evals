---
name: review
description: Adversarial review of the current change — the gates, a reviewer against the invariants in AGENTS.md, a skeptic for every serious finding, and a report committed to verification/reviews/.
disable-model-invocation: true
argument-hint: "[base-ref, default origin/master]"
allowed-tools: Read Grep Glob Bash(git diff *) Bash(git log *) Bash(git status *) Bash(uv run *)
---

Review the change between the base `$ARGUMENTS` (use `origin/master` when it is empty) and the
working tree.

1. Run `uv run python -m verification.gates`. A red gate is a finding in its own right: record it
   and continue.
2. Collect the change: `git diff <base>` plus the untracked files listed by `git status --short`.
   Ask the author for a one-line description if there is none.
3. Give the change-reviewer subagent the diff and the description.
4. For every finding of severity critical or major, give the finding-skeptic subagent that finding
   and the diff. Keep the finding only if the skeptic answers CONFIRMED; keep minor findings as
   reported.
5. Write the report to `verification/reviews/<YYYY-MM-DD>-<short head sha>.md`: the gates' result,
   the verdict, every confirmed finding with its evidence mark, and every rejected finding with the
   skeptic's reason. Do not edit any other file.
6. Reply with the verdict and the path of the report.
