"""Test ratchet: the suite may grow, it must not shrink.

The gate runs the suite and compares it with verification/test_inventory.json: every recorded test
must still exist, and every skipped test must be on the recorded list of allowed skips, each with
its reason. Deleting a test, or skipping one that was not skipped before, fails this gate even when
every remaining test passes, which is exactly how a coding agent under pressure turns a red suite
green. Tests and skips are tracked by id, not by count: a deleted test replaced by a trivial one
keeps the count, and some skips depend on the platform (the politeness lock is Windows-only, so its
tests skip on Linux CI).

After adding tests or a deliberate skip, update the inventory in the same commit with `--update`:
it records the current tests and adds the current skips to the allowed list (it never removes an
allowed skip).

    uv run python -m verification.test_ratchet             # check
    uv run python -m verification.test_ratchet --update    # record the current state
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import unittest
from pathlib import Path

INVENTORY = Path(__file__).resolve().with_name("test_inventory.json")


def _ids(suite: unittest.TestSuite) -> list[str]:
    out: list[str] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            out.extend(_ids(item))
        else:
            out.append(item.id())
    return out


def observe(start_dir: str = "tests") -> tuple[set[str], dict[str, str]]:
    """Discover and run the suite quietly from the current directory, as the unit-tests gate does.
    Returns the ids of every test and the skipped ones with their reasons."""
    suite = unittest.TestLoader().discover(start_dir)
    ids = set(_ids(suite))
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    return ids, {case.id(): str(reason) for case, reason in result.skipped}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="The test suite may grow, it must not shrink")
    ap.add_argument("--update", action="store_true",
                    help="record the current tests and add the current skips to the allowed list")
    args = ap.parse_args()

    ran, skipped = observe()
    recorded = (json.loads(INVENTORY.read_text(encoding="utf-8")) if INVENTORY.exists()
                else {"tests": [], "allowed_skips": {}})
    if args.update:
        allowed = dict(sorted({**recorded["allowed_skips"], **skipped}.items()))
        INVENTORY.write_text(json.dumps({"tests": sorted(ran), "allowed_skips": allowed},
                                        ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8", newline="\n")
        print(f"inventory updated: {len(ran)} tests, {len(allowed)} allowed skip(s)")
        return 0

    missing = sorted(set(recorded["tests"]) - ran)
    new_skips = sorted(set(skipped) - set(recorded["allowed_skips"]))
    added = len(ran - set(recorded["tests"]))
    print(f"tests {len(ran)} (recorded {len(recorded['tests'])}, new {added}); "
          f"skipped {len(skipped)}, of them not allowed {len(new_skips)}")
    problems = []
    if missing:
        problems.append(f"{len(missing)} recorded test(s) gone: {', '.join(missing[:8])}")
    if new_skips:
        problems.append(f"{len(new_skips)} skip(s) not on the allowed list: "
                        f"{', '.join(new_skips[:8])}")
    if problems:
        print("RATCHET: " + "; ".join(problems) + ". Removing or skipping tests needs a "
              "deliberate --update in the same commit, where a reviewer can see it.")
        return 1
    if added:
        print(f"note: {added} new test(s) are not in the inventory yet; --update records them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
