"""Tally the graded review-layer benchmark into the numbers the protocol reports.

grades.json is written by hand after every review has finished, one entry per item:

  {"item07": {"a_raw":     {"caught": true,  "false_alarms": 0},
              "a_skeptic": {"caught": true,  "false_alarms": 0},
              "b_raw":     {"caught": false, "false_alarms": 1},
              "note": "why, in one sentence"}}

"caught" counts only on bug items and "false_alarms" (critical or major findings that are not real)
only on clean items; key.json says which item is which.

    <python> tally.py            # prints the summary and the per-item table as Markdown
"""

from __future__ import annotations

import json
from pathlib import Path

BENCH = Path(__file__).resolve().parent
COLUMNS = (("change-reviewer alone", "a_raw"),
           ("change-reviewer + finding-skeptic (the layer as shipped)", "a_skeptic"),
           ("ECC code-reviewer", "b_raw"))


def main() -> int:
    key = json.loads((BENCH / "key.json").read_text(encoding="utf-8"))
    grades = json.loads((BENCH / "grades.json").read_text(encoding="utf-8"))
    missing = sorted(set(key) - set(grades))
    if missing:
        raise SystemExit(f"!! not graded yet: {', '.join(missing)}")
    bugs = sorted(i for i, k in key.items() if k["kind"] == "bug")
    clean = sorted(i for i, k in key.items() if k["kind"] == "clean")

    print("| Reviewer | Bugs caught | Clean changes with a false alarm | False alarms |")
    print("|---|---|---|---|")
    for label, col in COLUMNS:
        caught = sum(bool(grades[i][col]["caught"]) for i in bugs)
        flagged = sum(1 for i in clean if grades[i][col]["false_alarms"])
        alarms = sum(int(grades[i][col]["false_alarms"]) for i in clean)
        print(f"| {label} | {caught} of {len(bugs)} | {flagged} of {len(clean)} | {alarms} |")

    def mark(item: str, col: str) -> str:
        g = grades[item][col]
        if key[item]["kind"] == "bug":
            return "caught" if g["caught"] else "—"
        return f"{g['false_alarms']} false alarm(s)" if g["false_alarms"] else "clean"

    print("\n| Item | Source | Kind | Alone | With skeptic | ECC | Note |")
    print("|---|---|---|---|---|---|---|")
    for item in sorted(key):
        k = key[item]
        title = k.get("title", "")
        src = f"{k['src']}: {title}" if title else k["src"]
        print(f"| {item} | {src} | {k['kind']} | {mark(item, 'a_raw')} | "
              f"{mark(item, 'a_skeptic')} | {mark(item, 'b_raw')} | {grades[item].get('note', '')} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
