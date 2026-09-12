"""Tally the graded second review benchmark into the numbers the protocol reports.

grades2.json is written by hand after every review has finished, one entry per item:

  {"r2-item02": {"a_raw":     {"caught": ["W19"],        "false_alarms": 0},
                 "a_skeptic": {"caught": ["W19"],        "false_alarms": 0},
                 "b_raw":     {"caught": ["W19", "W13"], "false_alarms": 1},
                 "c_raw":     {"caught": [],             "false_alarms": 0},
                 "note": "why, in one sentence"}}

"caught" lists the planted defects a configuration named (it must be a subset of the item's defects
in key2.json); "false_alarms" counts its critical or major findings that name neither a planted
defect nor a demonstrable real one, on clean and bug items alike.

    <python> tally2.py            # prints the summary and the per-item table as Markdown
"""

from __future__ import annotations

import json
from pathlib import Path

BENCH = Path(__file__).resolve().parent
COLUMNS = (("change-reviewer alone", "a_raw"),
           ("change-reviewer + finding-skeptic (the layer as shipped)", "a_skeptic"),
           ("ECC code-reviewer, agent rules in the tree", "b_raw"),
           ("ECC code-reviewer, agent rules removed", "c_raw"))


def main() -> int:
    key = json.loads((BENCH / "key2.json").read_text(encoding="utf-8"))
    grades = json.loads((BENCH / "grades2.json").read_text(encoding="utf-8"))
    missing = sorted(set(key) - set(grades))
    if missing:
        raise SystemExit(f"!! not graded yet: {', '.join(missing)}")
    planted = {item: [b["id"] for b in k["bugs"]] for item, k in key.items()}
    total = sum(len(v) for v in planted.values())
    for item, g in grades.items():
        for _, col in COLUMNS:
            extra = set(g[col]["caught"]) - set(planted[item])
            if extra:
                raise SystemExit(f"!! {item}.{col}: {sorted(extra)} is not planted there")

    print("| Reviewer | Defects found | Items with a false alarm | False alarms |")
    print("|---|---|---|---|")
    for label, col in COLUMNS:
        found = sum(len(grades[i][col]["caught"]) for i in key)
        flagged = sum(1 for i in key if grades[i][col]["false_alarms"])
        alarms = sum(int(grades[i][col]["false_alarms"]) for i in key)
        print(f"| {label} | {found} of {total} | {flagged} of {len(key)} | {alarms} |")

    def cell(item: str, col: str) -> str:
        g, want = grades[item][col], planted[item]
        got = [b for b in want if b in g["caught"]]
        base = ("—" if not want else
                "all" if len(got) == len(want) else
                "none" if not got else ", ".join(got))
        fa = g["false_alarms"]
        return base + (f" (+{fa} false)" if fa else "")

    print("\n| Item | Change | Defects | Alone | With skeptic | ECC | ECC without rules | Note |")
    print("|---|---|---|---|---|---|---|---|")
    for item in sorted(key):
        k = key[item]
        defects = ", ".join(b["id"] for b in k["bugs"]) or "clean"
        print(f"| {item} | {k['src']} ({len(k['files'])} files) | {defects} | "
              f"{cell(item, 'a_raw')} | {cell(item, 'a_skeptic')} | {cell(item, 'b_raw')} | "
              f"{cell(item, 'c_raw')} | {grades[item].get('note', '')} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
