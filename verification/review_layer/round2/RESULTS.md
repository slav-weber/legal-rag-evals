# Review-layer benchmark, round 2: results

Run on 2026-09-12 under [`PROTOCOL.md`](PROTOCOL.md), which was committed with the items and the key
before any reviewer ran. Every raw output is in [`raw/`](raw/): `r2-itemNN.reviewer-a.md` is this
repository's change-reviewer, `.reviewer-b.md` the generic ECC reviewer on the tree with the agent
rules, `.reviewer-c.md` the same reviewer on the tree without them, and `.skeptic-N.md` the
finding-skeptic on the change-reviewer's Nth serious finding, which is stored in
[`raw/findings/`](raw/findings/). The grading is in [`grades.json`](grades.json), the key in
[`key.json`](key.json). Round 1 is one directory up.

## The numbers

| Reviewer | Defects found | Items with a false alarm | False alarms |
|---|---|---|---|
| change-reviewer alone | 10 of 10 | 0 of 6 | 0 |
| change-reviewer + finding-skeptic (the layer as shipped) | 10 of 10 | 0 of 6 | 0 |
| ECC code-reviewer, agent rules in the tree | 10 of 10 | 0 of 6 | 0 |
| ECC code-reviewer, agent rules removed | 10 of 10 | 0 of 6 | 0 |

- Verdicts: BLOCK from all three configurations on all four bug items, PASS from all three on both
  clean items. On the clean items no configuration raised a finding of any severity, and in the whole
  round no configuration raised a finding that is not a planted defect — not one false alarm, and not
  one minor finding either.
- Every serious finding named the planted file, the changed line and the changed behaviour, and every
  one was marked `[LIVE]`: the reviewer had run something. Several ran the whole suite and reported
  the exact failing test; one ran the lint gate and quoted its rule id.
- The skeptic examined all ten serious findings of the change-reviewer and confirmed all ten. Again
  it had no false finding to remove. It did correct three write-ups: that no gate runs `--mode noise`
  today, so that defect's damage is operator-facing rather than CI-facing; that one "silent" hole is
  silent at runtime but red in CI; and that a finding cited the wrong invariant number.
- The three configurations differ by nothing measurable here. They even agree on severity most of the
  time; where they disagree it is critical against major on the same line.

## Every item

| Item | Change | Defects | Alone | With skeptic | ECC | ECC without rules |
|---|---|---|---|---|---|---|
| r2-item01 | K05, 1 file, 103 changed lines | clean | — | — | — | — |
| r2-item02 | K03, 4 files, 209 changed lines | W19, W13 | all | all | all | all |
| r2-item03 | K06, 2 files, 82 changed lines | clean | — | — | — | — |
| r2-item04 | K02, 2 files, 230 changed lines | W09, W11 | all | all | all | all |
| r2-item05 | K04, 6 files, 249 changed lines | W18, W20, W14 | all | all | all | all |
| r2-item06 | K01, 3 files, 250 changed lines | W02, W05, W08 | all | all | all | all |

What the defects are, and where every configuration found them:

- **W19 / W13** (`r2-item02`) — the canonical `nreg` dropped from the freshness alias map
  (`probe.py:101`), and an unclosed amendment quote demoted to a warning so the parse exits 0
  (`parse_structure.py:841`).
- **W09 / W11** (`r2-item04`) — the retrieval eval matching an article by bare string prefix
  (`retrieval_eval.py:134`), and the replay-noise gate losing its gold-flip leg (`harness.py:529`).
- **W18 / W20 / W14** (`r2-item05`) — a citation label dropping its block ordinal
  (`chunk.py:139`), the units ledger flagging only counts that shrank (`units_ledger.py:56`), and the
  Rada HTTP helper following redirects by default, which disables the routing guard
  (`_common.py:58`).
- **W02 / W05 / W08** (`r2-item06`) — the exact-lookup regex dropping the article suffix so
  `ст.210-1` is served as `ст.210` (`retrieval.py:310`), candidate dedup grouping by article number
  across acts (`generate.py:117`), and the dev server binding to every interface (`api/main.py:164`).

## What this shows, and what it does not

- **Harder items did not separate the reviewers.** Round 1 was at the ceiling with one small defect
  per diff. Round 2 gave every reviewer a 82-to-250-line refactor with two or three defects hidden
  inside it, and all three configurations still found everything with no false alarm. Whatever
  separates these prompts, it is not visible at this difficulty either.
- **The ablation measured less than it was meant to.** Removing `AGENTS.md`, `CLAUDE.md` and
  `.claude/` does not remove the written invariants from the tree: `docs/ARCHITECTURE.md` lists five
  of them under "Invariants, in one place", and `README.md` and `verification/README.md` both
  describe the rules and point at them. The configuration without the rules cited "invariant 3" twice
  — the numbering of the documentation, not of `AGENTS.md` — and cited `ARCHITECTURE.md` by name on
  two items. So this round shows that removing the agent-rule files changes nothing, not that written
  invariants change nothing. A real ablation has to strip the documented invariants too, and that
  tree is no longer this repository.
- **Eight of the ten defects are visible to the gates.** The defects come from the v4 catalogue,
  which the gates scored 17 of 20; only W05 and W11 are among the three the gates missed. The
  reviewers ran the suite, so on eight defects the gates did part of the work and the reviewer read
  the failure and explained it. The two gate-invisible defects were also found by all three
  configurations, on argument from the code and a live run — that is the part of the number that is
  review and not gates.
- **The skeptic's precision gain is still unmeasured**, for the third measurement running: there was
  no false finding to remove. What is measured again is that it threw away no true finding, and that
  it sharpens the write-ups.
- **Planted defects inside a refactor are still planted defects.** Each is one deliberate edit with a
  plausible story. A defect that emerges from the logic of a large change — two correct-looking
  halves that are wrong together — is not in this benchmark, and is the obvious next thing to try.

## Deviations and contamination, stated after the run

- **A tree carried a file that names two of the defects.** The trees exclude
  `verification/seeded_bugs/`, `verification/reports/` and `verification/review_layer/`, but not
  `verification/README.md`, which tabulates the v4 misses and so names W05 and W11 by their effect.
  Three of the 28 outputs cite it: `r2-item06.reviewer-a.md` and `r2-item06.skeptic-3.md` (W05) and
  `r2-item04.skeptic-2.md` (W11). In each case the citation comes after the run's own `[LIVE]`
  reproduction and is used as corroboration, and the other two configurations found the same two
  defects on the same trees without citing it — but the file was there, so those two defects are
  contaminated and the honest reading of this round is 8 clean defects of 8 for every configuration,
  plus 2 on which the tree could be read. Next round the trees exclude `verification/README.md`.
- **The protocol's item description is slightly off.** It says one to three files per item; that
  holds for the six refactors (82 to 241 changed lines, one to three files), but a planted defect can
  sit in a file the refactor never touched, so `r2-item05` reaches six files and the items span 82 to
  250 changed lines. The diffs published here are what the reviewers read.
- As in round 1, the reviewers ran as general-purpose subagents told to follow their instructions
  file; the tool limits in the agent files were stated in the instructions, not enforced by the
  harness.

## Reproduce

[`tools/`](tools/) holds the scripts as they were run: `build.py` builds the trees, the diffs and the
key, `prompts.py` writes the instructions files, `skeptics.py` prepares one skeptic per serious
finding, and `tally.py` produces the tables above. `items.src.json` is the item list before
shuffling, and `clean/` the six refactors with their authors' one-line descriptions and notes. The
paths at the top of the scripts point at the author's machine. ECC's `agents/code-reviewer.md` at
`c9148d0` is not included and has to be fetched.
