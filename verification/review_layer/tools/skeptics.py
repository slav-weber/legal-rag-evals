"""Prepare one skeptic instruction file per critical or major finding of reviewer-a.

    <python> skeptics.py        # every rb/raw/itemNN.reviewer-a.md not prepared yet

The findings are the JSON array reviewer-a is asked to give after its verdict line. Each critical or
major finding is written to rb/findings/<item>.a.<n>.json and gets rb/prompts/<item>.skeptic-<n>.md
through prompts.py. Prints one line per prepared skeptic, and one line per item without any.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
RB = BENCH.parent / "rb"
RAW, FINDINGS, PROMPTS = RB / "raw", RB / "findings", RB / "prompts"


def parse(text: str) -> list[dict] | None:
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    blob = fenced.group(1) if fenced else text[text.find("["): text.rfind("]") + 1]
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def main() -> int:
    FINDINGS.mkdir(parents=True, exist_ok=True)
    for raw in sorted(RAW.glob("item*.reviewer-a.md")):
        item = raw.name.split(".")[0]
        data = parse(raw.read_text(encoding="utf-8"))
        if data is None:
            print(f"!! {item}: no parsable findings array")
            continue
        serious = [f for f in data if str(f.get("severity", "")).lower() in ("critical", "major")]
        if not serious:
            print(f"{item}: no critical or major finding ({len(data)} in total)")
        for n, finding in enumerate(serious, 1):
            if (PROMPTS / f"{item}.skeptic-{n}.md").exists():
                continue
            path = FINDINGS / f"{item}.a.{n}.json"
            path.write_text(json.dumps(finding, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
            subprocess.run([sys.executable, str(BENCH / "prompts.py"), "skeptic", item, str(n),
                            str(path)], check=True, capture_output=True)
            print(f"{item} skeptic-{n}: {finding.get('severity')} {finding.get('file')}:"
                  f"{finding.get('line')} {str(finding.get('defect'))[:100]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
