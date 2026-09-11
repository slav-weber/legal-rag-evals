# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- `/review` (`.claude/skills/review/`) runs the adversarial review described in AGENTS.md, with the
  `change-reviewer` and `finding-skeptic` subagents in `.claude/agents/`.
- A Stop hook (`.claude/hooks/gates_before_stop.py`) keeps you from finishing while a gate is red
  after you changed Python files. When it fires, fix the cause; never skip or weaken a test to
  silence it.
- Editing the test inventory, the seeded-bug catalogues, the reports or CI asks for approval
  (`.claude/settings.json`).
