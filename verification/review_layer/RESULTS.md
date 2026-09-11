# Review-layer benchmark: results

Run on 2026-09-11 under the protocol in [`PROTOCOL.md`](PROTOCOL.md), which was committed before any
reviewer ran. Every raw output is in [`raw/`](raw/): `itemNN.reviewer-a.md` is the
change-reviewer, `itemNN.reviewer-b.md` the generic code-reviewer of everything-claude-code, and
`itemNN.skeptic-N.md` the finding-skeptic on the change-reviewer's Nth serious finding, which is
stored in `raw/findings/`. The grading is in [`grades.json`](grades.json), and which item is which
in [`key.json`](key.json).

## The numbers

| Reviewer | Bugs caught | Clean changes with a false alarm |
|---|---|---|
| change-reviewer alone | 10 of 10 | 0 of 9 |
| change-reviewer + finding-skeptic (the layer as shipped) | 10 of 10 | 0 of 9 |
| generic code-reviewer (ECC, `c9148d0`) | 10 of 10 | 0 of 9 |

- Verdicts: both reviewers gave BLOCK on all ten bug items. On the nine clean items both gave PASS,
  with one exception: the generic reviewer gave CONCERNS on item07 for a minor finding (no test for a
  new error branch), which the protocol does not count.
- Every serious finding on a bug item named the planted file and line and the changed behaviour, and
  every one was marked [LIVE]: the reviewer had run something, usually the code before and after the
  change side by side. The change-reviewer raised 14 serious findings on the ten bugs, the generic
  reviewer 11.
- The skeptic examined all 14 serious findings of the change-reviewer and confirmed all 14. It had
  no false finding to remove and rejected no true one.
- Both reviewers cited an invariant of `AGENTS.md` on seven of the ten bug items. The generic
  reviewer is not told about `AGENTS.md`. It found the file in the tree, because its instructions
  tell it to look for project conventions.

## Every item

| Item | Source | Kind | Alone | With skeptic | ECC | Note |
|---|---|---|---|---|---|---|
| item01 | V08: A generation-provider outage is answered as a 200 abstain | bug | caught | caught | caught | both name generate.py:305, the catch-all that turns a provider error into an abstain; the skeptic confirmed all three of reviewer-a's findings |
| item02 | R2 | clean | clean | clean | clean | PASS from both |
| item03 | V05: A dovidka without legal theses is accepted with no citation | bug | caught | caught | caught | both name generate.py:317, the citation rule no longer applied to an answer without theses (critical); confirmed |
| item04 | R3 | clean | clean | clean | clean | PASS from both |
| item05 | R4 | clean | clean | clean | clean | PASS from both |
| item06 | V19: The units ledger no longer flags units injected into an edition | bug | caught | caught | caught | both name units_ledger.py:56, growth inside a known edition no longer flagged; both findings of reviewer-a confirmed |
| item07 | C03 | clean | clean | clean | clean | PASS from reviewer-a; one minor finding from ECC (no test for the new error branch), not counted |
| item08 | C04 | clean | clean | clean | clean | PASS from both |
| item09 | V11: Golden cases that raise are skipped and the gate stays green | bug | caught | caught | caught | both name harness.py:365-366, a golden case that raises is skipped and the gate stays green; both findings of reviewer-a confirmed |
| item10 | V15: The probe's previous signal can be a failed probe's NULL | bug | caught | caught | caught | both name probe.py:208, the previous signal can be a failed probe's NULL; confirmed |
| item11 | V13: An unclosed amendment quote no longer fails the parse run | bug | caught | caught | caught | both name parse_structure.py:841, an unclosed quote no longer fails the run; confirmed |
| item12 | V14: fetch_texts skips the polite pause between Rada requests | bug | caught | caught | caught | both name fetch_texts.py:78, the polite pause skipped (reviewer-a critical, ECC major); confirmed |
| item13 | V18: The amendment-marker pattern turns greedy and deletes legal text | bug | caught | caught | caught | both name parse_structure.py:83, the greedy marker pattern deletes legal text between two notes; confirmed |
| item14 | R1 | clean | clean | clean | clean | PASS from both |
| item15 | C01 | clean | clean | clean | clean | PASS from both |
| item16 | V07: The USER_DATA tripwire is logged and skipped on generation | bug | caught | caught | caught | both name llm_client.py:325, the user-data tripwire swallowed (critical); confirmed |
| item17 | C05 | clean | clean | clean | clean | PASS from both |
| item18 | V01: Candidate channels ignore the as_of date and gate on today | bug | caught | caught | caught | both name retrieval.py:180, the channels no longer receive as_of (critical); confirmed |
| item19 | C02 | clean | clean | clean | clean | PASS from both |

## What this shows, and what it does not

- **Agent review closes the gap the gates leave on these bugs.** The gates missed all ten; both
  reviewers found all ten, and neither raised a serious alarm on a clean change. Each review took 3
  to 10 minutes of agent time, and the usage reported per review was roughly 110 to 225 thousand
  tokens; the gates take seconds. Review is the expensive layer. That is why it runs on what the
  gates cannot express, not in their place.
- **It does not tell the two reviewers apart.** Both are at the ceiling, and the generic reviewer had
  the same `AGENTS.md` in the tree and used it. At this size the measured difference between the
  prompts is zero. Showing one would take harder items: larger diffs, several defects in one change,
  descriptions that argue for the change, and one run of the generic reviewer without `AGENTS.md`,
  to isolate what the invariants add.
- **It does not measure what the skeptic is worth.** There was no false finding among the serious
  ones, so the skeptic's gain in precision is unmeasured here. What is measured is that it threw
  away no true finding.
- **Single planted defects are easier than real ones.** Each bug is one small change with a
  plausible story, in a tree the reviewer can run. Real changes are larger and mix intent with
  accident.

## Deviations from the protocol

- Sixteen reviewer runs and three skeptic runs stopped early on an API usage limit (HTTP 429). Two of
  those reviewer runs (item01 reviewer-a, item07 reviewer-a) had already written their answer. The
  other fourteen and the three skeptics were resumed from where they stopped, with this message:
  "You stopped early because of an API error, before your final answer. Continue the same task from
  where you stopped, following the same instructions file, and finish by writing your final answer
  to the file it names." No run was restarted from scratch, and no answer was edited.
- As the protocol says, the reviewers ran as general-purpose subagents told to follow their
  instructions file. The tool limits in their agent files (Read, Grep, Glob, Bash) were stated in the
  instructions, not enforced by the harness.

## Reproduce

`tools/` holds the scripts as they were run: `build.py` builds the trees, the diffs and the key,
`prompts.py` writes the instructions files, `skeptics.py` prepares one skeptic per serious finding,
and `tally.py` produces the tables above. `items.src.json` is the item list before shuffling. The
paths at the top of the scripts point at the author's machine. ECC's `agents/code-reviewer.md` at
`c9148d0` is not included and has to be fetched.
