"""Write the instructions file of every (item, reviewer) pair of the review-layer benchmark.

    <python> prompts.py reviewers          # rb/prompts/<item>.reviewer-a.md and .reviewer-b.md
    <python> prompts.py skeptic ITEM N FINDING_JSON_FILE   # rb/prompts/<item>.skeptic-<N>.md

reviewer-a is the change-reviewer of legal-rag-evals, reviewer-b the ECC code-reviewer at c9148d0
with its output section replaced by the change-reviewer's, so both are graded the same way. Both
get the same setting note. The skeptic is the finding-skeptic, given one finding of reviewer-a.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
RB = BENCH.parent / "rb"
PROMPTS = RB / "prompts"
RAW = RB / "raw"
REPO = Path("E:/Web Dev/my-projects/legal-rag-evals")
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
    ecc = body(BENCH / "ecc" / "code-reviewer.md")
    start, end = ecc.index("## Review Output Format"), ecc.index("## Project-Specific Guidelines")
    replaced = ("## Review Output Format\n\nFor this run, report in the following format. Severity: "
                "CRITICAL is critical, HIGH is major, MEDIUM and LOW are minor.\n\n"
                + output[len("## Output"):].lstrip() + "\n")
    return mine, ecc[:start] + replaced + ecc[end:]


def main() -> int:
    PROMPTS.mkdir(parents=True, exist_ok=True)
    items = {it["item"]: it for it in json.loads((BENCH / "items.json").read_text(encoding="utf-8"))}
    RAW.mkdir(parents=True, exist_ok=True)
    if sys.argv[1] == "reviewers":
        mine, ecc = reviewer_texts()
        for name, it in items.items():
            for label, text in (("reviewer-a", mine), ("reviewer-b", ecc)):
                note = SETTING.format(tree=it["tree"], diff=it["diff"], py=PY,
                                      description=it["description"],
                                      raw=(RAW / f"{name}.{label}.md").as_posix())
                (PROMPTS / f"{name}.{label}.md").write_text(note + text, encoding="utf-8",
                                                           newline="\n")
        print(f"{2 * len(items)} reviewer instruction files in {PROMPTS}")
        return 0
    if sys.argv[1] == "skeptic":
        name, n, finding_file = sys.argv[2], sys.argv[3], Path(sys.argv[4])
        it = items[name]
        note = SETTING.format(tree=it["tree"], diff=it["diff"], py=PY,
                              description=it["description"],
                              raw=(RAW / f"{name}.skeptic-{n}.md").as_posix())
        finding = finding_file.read_text(encoding="utf-8").strip()
        text = (note + body(REPO / ".claude" / "agents" / "finding-skeptic.md")
                + "\n## The finding\n\n```json\n" + finding + "\n```\n")
        out = PROMPTS / f"{name}.skeptic-{n}.md"
        out.write_text(text, encoding="utf-8", newline="\n")
        print(out.as_posix())
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
