# Review-layer benchmark: protocol

Fixed and committed before any reviewer ran. The results, every raw output and the grading are
published next to this file after the run.

## The question

What does the review layer (`AGENTS.md`, the `change-reviewer`, the `finding-skeptic`, as `/review`
runs them) add on top of the deterministic gates, and what does it cost in false alarms? A generic
reviewer is the baseline: the `code-reviewer` agent of everything-claude-code (ECC),
`agents/code-reviewer.md` at commit `c9148d0`.

## Items

Nineteen changes, each a diff plus the tree after it (`items.json`, `items/`):

- **Ten bugs:** every bug of the blind third catalogue that the gates missed in
  `../reports/seeded-bugs-2026-09-11-v3.md`: V01, V05, V07, V08, V11, V13, V14, V15, V18, V19. The
  gates stop the other ten; review matters where they do not.
- **Nine clean changes** that break nothing. Four are real commits of this repository: R1 and R2
  (lint cleanups from `1454b63`), R3 (the `stub-hallucinate` backend from `6dba4fd`), R4 (the
  portable politeness lock, `616c621`). Five were written for this benchmark by an agent that did
  not know the planted bugs, and each was checked against the gates and against the code before it
  (C01 and C02 refactors, C03 a clearer error, C04 type hints, C05 a cache).
- The tree of every item is `git archive 4664512` without `verification/seeded_bugs/` and
  `verification/reports/`, so no tree holds a catalogue or a report, with the change applied. For
  R1 to R4 the change is already in that tree, and the diff is the original commit's patch.
- The items are shuffled with seed 20260911 and named item01 to item19. A reviewer sees only its
  item's tree, its diff and a one-line description written as the change's author would write it.
  For a bug the description is the reasonable intent from the bug's story, never the defect. Which
  items are bugs is recorded in `key.json`, which no reviewer sees.

## Reviewers

The same model for every run (Claude Opus 5). Each reviewer runs as a general-purpose Claude Code
subagent told to read one instructions file and follow it. The file is the setting note below plus
the reviewer's own instructions. The tools a reviewer may use are Read, Grep, Glob and Bash, as
their agent files declare; in this setting that limit is stated in the instructions, not enforced
by the harness.

1. **reviewer-a:** the body of `.claude/agents/change-reviewer.md`, unchanged.
2. **reviewer-b:** the body of ECC's `agents/code-reviewer.md` at `c9148d0`, unchanged except that
   its "Review Output Format", "Summary Format" and "Approval Criteria" sections are replaced by the
   change-reviewer's output section, so both are graded the same way. The replacement begins: "For
   this run, report in the following format. Severity: CRITICAL is critical, HIGH is major, MEDIUM
   and LOW are minor." ECC's text is not republished here.
3. **skeptic:** the body of `.claude/agents/finding-skeptic.md`, unchanged, given one critical or
   major finding of reviewer-a together with the same setting. This is the `/review` pipeline. ECC
   has no such stage: its raw output is what it ships.

The setting note, identical for every reviewer apart from the paths and the description:

```text
## Setting of this run

- The change described below is already applied in the tree at `<tree>`. Work only inside that
  tree. Besides it you may read exactly two files: the diff `<diff>` and this instructions file.
- The tree is not a git repository and there is no base ref: the change is the diff file. Where
  the instructions below say to run git, read the diff file instead.
- To run Python, from the tree root: `cd "<tree>" && PYTHONDONTWRITEBYTECODE=1 "<python>" -c "..."`
  (or `-m unittest ...` in place of `-c`). `uv` is not available for this tree. There is no network.
- Do not create, change or delete any file, with one exception: when you are done, write your
  final answer, exactly as you give it, to `<raw output file>`.
- The author's description of the change: "<description>"
```

## Grading, fixed now

- A bug item is **caught** by a reviewer when at least one of its critical or major findings names
  the planted defect: the right file and the changed behaviour, not merely a nearby line. For the
  layer as shipped, the finding must also be CONFIRMED by the skeptic.
- On a clean item every critical or major finding is a **false alarm**, unless it names a real
  defect that can be demonstrated with a command. Such a finding is reported as a finding about the
  clean set and is not counted as a false alarm.
- Minor findings are published and not counted.
- The grading is done against `key.json` after every review has finished. Every raw output is
  published, so the grading can be checked and disputed.
- Reported for (a) reviewer-a alone, (b) reviewer-a with the skeptic, the layer as shipped, and (c)
  reviewer-b: the bug items caught out of ten, and the false alarms on the nine clean items. The
  verdict line of each run is reported as well.

## Known limits, stated before the run

- The invariants in `AGENTS.md` were written after the held-out measurement and name some of its
  classes. The third catalogue was written without seeing `AGENTS.md`, but the layer is not blind to
  the defect classes of earlier catalogues. A reviewer can also read `verification/README.md`,
  which describes earlier misses; both reviewers can.
- The descriptions were written by the author of this benchmark, from the bug stories. A different
  wording could make a defect easier or harder to see.
- One run per reviewer and item. Model output varies between runs, so the numbers are one sample.
- The bug items are the gates' misses, so this measures the layer where the gates are weakest, not
  its share of all bugs.
- Ten bugs and nine clean changes are small numbers.
