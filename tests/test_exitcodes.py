"""Smoke: the shared honest exit-code convention + per-site mappings.

    uv run python tests/test_exitcodes.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines import exitcodes as ec  # noqa: E402
from pipelines.ksu.snapshot import exit_code as ksu_exit  # noqa: E402


class Convention(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((ec.OK, ec.FAIL, ec.SKIP, ec.STALE), (0, 1, 2, 3))

    def test_fail_if(self):
        self.assertEqual(ec.fail_if(0), ec.OK)
        self.assertEqual(ec.fail_if(3), ec.FAIL)
        self.assertEqual(ec.fail_if([]), ec.OK)
        self.assertEqual(ec.fail_if(0, undercount=True), ec.FAIL)

    def test_worst_severity_not_bitwise(self):
        # FAIL dominates; FAIL+SKIP must NOT collapse to STALE (the bitwise-OR bug).
        self.assertEqual(ec.worst([ec.OK, ec.SKIP]), ec.SKIP)
        self.assertEqual(ec.worst([ec.FAIL, ec.SKIP]), ec.FAIL)
        self.assertEqual(ec.worst([ec.STALE, ec.SKIP]), ec.STALE)
        self.assertEqual(ec.worst([ec.OK, ec.OK]), ec.OK)
        self.assertEqual(ec.worst([]), ec.OK)


class KsuExit(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(ksu_exit([], []), ec.OK)

    def test_errors_fail(self):
        self.assertEqual(ksu_exit(["x: HTTP 500"], []), ec.FAIL)

    def test_bad_char_fail(self):
        self.assertEqual(ksu_exit([], ["y"]), ec.FAIL)

    def test_pure_defer_is_skip(self):
        # nothing saved, only a planned budget defer → SKIP(2)
        self.assertEqual(ksu_exit([], [], deferred=5, saved=0), ec.SKIP)

    def test_defer_with_progress_is_ok(self):
        self.assertEqual(ksu_exit([], [], deferred=5, saved=3), ec.OK)

    def test_errors_win_over_defer(self):
        self.assertEqual(ksu_exit(["e"], [], deferred=5, saved=0), ec.FAIL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
