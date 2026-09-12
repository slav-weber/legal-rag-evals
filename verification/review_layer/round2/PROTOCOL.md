# Review-layer benchmark, round 2: protocol

Fixed and committed before any reviewer ran. The results, every raw output and the grading are
published next to this file after the run. Round 1 is one directory up.

## The question

Round 1 put both reviewers at the ceiling: one planted defect per small diff, 10 of 10 for each, no
false alarm on nine clean changes. It could not tell the two reviewers apart, and it said nothing
about what the written invariants add, because the generic reviewer read `AGENTS.md` too. Round 2
makes the items harder in the three ways round 1 could not answer:

- **Large changes.** Every item is a behaviour-preserving refactor of 82 to 241 changed lines across
  one to three files, written by an agent that never opened a catalogue, a report or round 1.
- **Several defects at once.** A bug item carries two or three planted defects inside that refactor,
  so a reviewer has to find them all, not one.
- **An ablation.** The same generic reviewer runs twice: once on a tree that carries the
  repository's agent rules (`AGENTS.md`, `CLAUDE.md`, `.claude/`) and once on a tree without them.

## Items

Six items on git `129470d`: four carrying ten planted defects between them (three, two, two and
three), and two clean.

- Each item is one diff and one tree: the refactor applied, then its defects planted with the
  benchmark's own `plant()`, so the defects sit inside the change. The diff a reviewer reads is the
  whole change, base to tree, refactor and defects together.
- The defects come from `../../seeded_bugs/catalogue_v4.py`, the fourth blind catalogue, and include
  both bugs the gates caught and bugs they missed: the question here is what review sees inside a
  large mixed diff, not what the gates miss. Where a defect's file is one the refactor touched, it
  lands inside the refactor's own hunks; all ten planted cleanly on top of the refactors.
- The six refactors were checked by their author against the gates (GREEN in every changed copy) and
  against a before-and-after comparison of every observable the touched code produces: returned
  values, the SQL and parameters issued against a recording cursor, rendered HTML, written files,
  stdout and exit codes. The dumps are byte-identical.
- The description a reviewer is given is the refactor author's own one-line summary. It never
  mentions a defect.
- Trees are `git archive` of that revision without `verification/seeded_bugs/`,
  `verification/reports/` and `verification/review_layer/`, so no tree carries a catalogue, a report
  or round 1's key.
- Items are shuffled with seed 20260912 and named `r2-item01`...; what each holds is in `key.json`,
  which no reviewer sees.

## Reviewers

The same model for every run (Claude Opus 5), the same tools (Read, Grep, Glob, Bash), no network,
and the same setting note as round 1. Each reviewer runs as a general-purpose Claude Code subagent
told to read one instructions file and follow it; the tool limits of the agent files are stated in
the instructions, not enforced by the harness.

1. **reviewer-a:** this repository's `change-reviewer` on the tree with the agent rules, plus the
   `finding-skeptic` on every critical or major finding. This is `/review` as shipped.
2. **reviewer-b:** ECC's `code-reviewer` at `c9148d0`, its output section replaced by the
   change-reviewer's, on the same tree.
3. **reviewer-c:** the same ECC reviewer, the same prompt, on the tree with `AGENTS.md`, `CLAUDE.md`
   and `.claude/` removed.

## Grading, fixed now

- A planted defect is **caught** when at least one critical or major finding names it: the right
  file and the changed behaviour, not merely a nearby line. For the layer as shipped (reviewer-a
  with the skeptic) the finding must also be CONFIRMED by the skeptic.
- The headline is defects caught out of ten, per configuration. Per item the report says whether
  all, some or none of its defects were found.
- A critical or major finding that names neither a planted defect nor a real defect that can be
  demonstrated with a command is a **false alarm**, on clean items and bug items alike. Round 1
  counted false alarms on clean items only; inside a large mixed diff the distinction matters, so
  the count now covers every item.
- Minor findings are published and never counted.
- Grading is done against `key.json` after every review has finished, and every raw output is
  published, so the grading can be checked and disputed.

## Known limits, stated before the run

- The refactors were written to preserve behaviour and were checked as described above, but a
  refactor that changed behaviour by accident would show up here as a false alarm. Any such case is
  reported as a finding about the clean material, not counted against the reviewer.
- One run per reviewer and item. Model output varies between runs; the numbers are one sample.
- The defects are catalogue defects: deliberate single changes with a plausible story, not defects
  that emerge from the logic of a large change itself.
- The ablation removes the written rules from the tree, not the model's own knowledge of the domain
  or of what such a system needs.
- Six items and ten defects are small numbers, and two clean items are a thin false-alarm base.
