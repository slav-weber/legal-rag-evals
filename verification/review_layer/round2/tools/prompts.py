"""Write the instructions file of every (item, reviewer) pair of the second review benchmark.

    <python> prompts2.py reviewers        # rb2/prompts/<item>.reviewer-{a,b,c}.md
    <python> prompts2.py skeptic ITEM N FINDING_JSON_FILE

reviewer-a is the change-reviewer of legal-rag-evals, on the tree that carries the agent rules.
reviewer-b is the ECC code-reviewer at c9148d0, with its output section replaced by the
change-reviewer's, on the same tree. reviewer-c is the same ECC reviewer on the tree with
AGENTS.md, CLAUDE.md and .claude/ removed: the ablation that asks what the written invariants add.
All three get the same setting note. The skeptic is the finding-skeptic, on one finding of
reviewer-a.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
RB = BENCH.parent / "rb2"
PROMPTS, RAW = RB / "prompts", RB / "raw"
REPO = Path("E:/Web Dev/my-projects/legal-rag-evals")
ECC = BENCH.parent / "review_bench" / "ecc" / "code-reviewer.md"
PY = (REPO / ".venv" / "Scripts" / "python.exe").as_posix()

SETTING = """## Setting of this run

- The change described below is already applied in the tree at `{tree}`. Work only inside that
  tree. Besides it you may read exactly two files: the diff `{diff}` and this instructions file.
- The tree is not a git repository and there is no base ref: the change is the diff file. Where
  the instructions below say to run git, read the diff file instead.
- To run Python, from the tree root: `cd "{tree}" && PYTHONDONTWRITEBYTECODE=1 "{py}" -c "..."`
  (or `-m unittest ...` in place of `-c`). `uv` is not available for this tree. There is no network.
- Do not create, change or delete any file, with one exception: when you are done, write your
  final answer, exactly as you give it, to `{raw}`.
- The author's description of the change: "{description}"

"""


def body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip() + "\n"


def reviewer_texts() -> tuple[str, str]:
    mine = body(REPO / ".claude" / "agents" / "change-reviewer.md")
    output = mine[mine.index("## Output"):]
    ecc = body(ECC)
    start, end = ecc.index("## Review Output Format"), ecc.index("## Project-Specific Guidelines")
    replaced = ("## Review Output Format\n\nFor this run, report in the following format. Severity: "
                "CRITICAL is critical, HIGH is major, MEDIUM and LOW are minor.\n\n"
                + output[len("## Output"):].lstrip() + "\n")
    return mine, ecc[:start] + replaced + ecc[end:]


def main() -> int:
    PROMPTS.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    items = {it["item"]: it for it in json.loads((BENCH / "items2.json").read_text(encoding="utf-8"))}
    if sys.argv[1] == "reviewers":
        mine, ecc = reviewer_texts()
        for name, it in items.items():
            for label, text, tree in (("reviewer-a", mine, it["tree"]),
                                      ("reviewer-b", ecc, it["tree"]),
                                      ("reviewer-c", ecc, it["tree_norules"])):
                note = SETTING.format(tree=tree, diff=it["diff"], py=PY,
                                      description=it["description"],
                                      raw=(RAW / f"{name}.{label}.md").as_posix())
                (PROMPTS / f"{name}.{label}.md").write_text(note + text, encoding="utf-8",
                                                           newline="\n")
        print(f"{3 * len(items)} reviewer instruction files in {PROMPTS}")
        return 0
    if sys.argv[1] == "skeptic":
        name, n, finding_file = sys.argv[2], sys.argv[3], Path(sys.argv[4])
        it = items[name]
        note = SETTING.format(tree=it["tree"], diff=it["diff"], py=PY,
                              description=it["description"],
                              raw=(RAW / f"{name}.skeptic-{n}.md").as_posix())
        text = (note + body(REPO / ".claude" / "agents" / "finding-skeptic.md")
                + "\n## The finding\n\n```json\n"
                + finding_file.read_text(encoding="utf-8").strip() + "\n```\n")
        out = PROMPTS / f"{name}.skeptic-{n}.md"
        out.write_text(text, encoding="utf-8", newline="\n")
        print(out.as_posix())
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
