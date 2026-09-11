"""Test ratchet: the suite may grow, it must not shrink.

Counts the tests the suite runs and the tests it skips, and compares both with
verification/test_inventory.json. Deleting a test or adding a skip fails this gate even when every
remaining test passes, which is exactly how a coding agent under pressure turns a red suite green.
After adding tests on purpose, raise the floor in the same commit: `--update`.

    uv run python -m verification.test_ratchet             # check
    uv run python -m verification.test_ratchet --update    # record the current counts
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import unittest
from pathlib import Path

INVENTORY = Path(__file__).resolve().with_name("test_inventory.json")


def count(start_dir: str = "tests") -> dict[str, int]:
    """Run the suite quietly from the current directory, as the unit-tests gate does, and count."""
    suite = unittest.TestLoader().discover(start_dir)
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    return {"tests": result.testsRun, "skipped": len(result.skipped)}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="The test suite may grow, it must not shrink")
    ap.add_argument("--update", action="store_true", help="record the current counts as the floor")
    args = ap.parse_args()

    now = count()
    if args.update:
        INVENTORY.write_text(json.dumps(now, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"inventory updated: {now['tests']} tests, {now['skipped']} skipped")
        return 0

    floor = json.loads(INVENTORY.read_text(encoding="utf-8"))
    print(f"tests {now['tests']} (floor {floor['tests']}), skipped {now['skipped']} "
          f"(ceiling {floor['skipped']})")
    problems = []
    if now["tests"] < floor["tests"]:
        problems.append(f"{floor['tests'] - now['tests']} test(s) fewer than recorded")
    if now["skipped"] > floor["skipped"]:
        problems.append(f"{now['skipped'] - floor['skipped']} more skipped test(s) than recorded")
    if problems:
        print("RATCHET: " + "; ".join(problems) + ". Removing or skipping tests needs a "
              "deliberate --update in the same commit, where a reviewer can see it.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
