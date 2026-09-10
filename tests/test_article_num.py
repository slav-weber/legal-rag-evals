"""Unit tests: _article_num disambiguates 1- and 2-digit collapsed superscripts, plus the
run/twin reconciliation helpers around it.

    uv run python tests/test_article_num.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.rada.parse_structure import (  # noqa: E402
    _article_num, _fix_superscript_runs, Unit, genuine_max, _expand_collapsed,
    reconcile_collapsed, _reconcile_point)


def _arts(paths):
    return [Unit(p, "article", i, None, "x", []) for i, p in enumerate(paths)]


class ArticleNum(unittest.TestCase):
    def test_sequence_163_superscripts(self):
        # 163, 163¹…163⁹ (single digit), 163¹⁰…163¹⁸ (two digits), then plain 164.
        base = None
        got = []
        for raw in ["163", "1631", "1639", "16310", "16318", "164"]:
            disp, base = _article_num(raw, base)
            got.append(disp)
        self.assertEqual(got, ["163", "163-1", "163-9", "163-10", "163-18", "164"])

    def test_base_not_reset_by_two_digit_superscript(self):
        _, base = _article_num("16310", "163")
        self.assertEqual(base, "163")  # superscript must NOT advance the base

    def test_genuine_article_after_predecessor(self):
        # genuine art.151 follows 150 (not a superscript of 15).
        self.assertEqual(_article_num("151", "150"), ("151", "151"))

    def test_single_digit_superscript(self):
        self.assertEqual(_article_num("151", "15"), ("15-1", "15"))

    def test_already_hyphenated_kept(self):
        self.assertEqual(_article_num("283-2", "283"), ("283-2", "283"))

    def test_orphan_long_number_does_not_poison_base(self):
        # wrong/absent base → store verbatim but keep base for the following articles.
        self.assertEqual(_article_num("16310", "200"), ("16310", "200"))

    def test_leading_zero_suffix_not_a_superscript(self):
        # "1630" is not 163⁰ (no zero superscript) → treated as plain/long, base kept.
        disp, base = _article_num("1630", "163")
        self.assertEqual(disp, "1630")
        self.assertEqual(base, "163")


class SuperscriptRuns(unittest.TestCase):
    def test_base_absent_run_converted(self):
        # ст.166 is marked «виключено» (repealed, absent) → 1661…16611 are 166¹…166¹¹.
        units = _arts([f"ст.166{k}" if k < 10 else f"ст.166{k}" for k in range(1, 12)])
        # paths: ст.1661..ст.1669, ст.16610, ст.16611
        n = _fix_superscript_runs(units)
        self.assertEqual(n, 11)
        self.assertEqual([u.path for u in units[:3]], ["ст.166-1", "ст.166-2", "ст.166-3"])
        self.assertEqual(units[-1].path, "ст.166-11")

    def test_two_adjacent_base_absent_runs(self):
        units = _arts(["ст.1651", "ст.1652", "ст.1661", "ст.1662", "ст.1663", "ст.167"])
        _fix_superscript_runs(units)
        self.assertEqual([u.path for u in units],
                         ["ст.165-1", "ст.165-2", "ст.166-1", "ст.166-2", "ст.166-3", "ст.167"])

    def test_guard_base_present_not_converted(self):
        # Civil Code (ЦК) shape: ст.130 present → ст.1301…1308 are genuine articles, left alone.
        units = _arts(["ст.130", "ст.1301", "ст.1302", "ст.1303"])
        n = _fix_superscript_runs(units)
        self.assertEqual(n, 0)
        self.assertEqual([u.path for u in units[1:]], ["ст.1301", "ст.1302", "ст.1303"])

    def test_lone_long_number_not_converted(self):
        # a single "ст.1651" with no ст.1652 following → not a run, left as-is.
        units = _arts(["ст.1651", "ст.200"])
        self.assertEqual(_fix_superscript_runs(units), 0)


class GenuineMax(unittest.TestCase):
    def test_dense_cluster_then_collapsed(self):
        paths = {f"ст.{n}" for n in range(1, 331)} | {"ст.163-10", "ст.283-2", "ст.861", "ст.1321"}
        self.assertEqual(genuine_max(paths), 330)  # collapsed 861/1321 excluded

    def test_hyphenated_base_counts(self):
        # article 121 exists only as ст.121-4 (plain 121 is «виключено») → genuine max = 121.
        paths = {f"ст.{n}" for n in range(1, 94)} | {"ст.121-4", "ст.1214"}
        self.assertEqual(genuine_max(paths), 121)


class ExpandCollapsed(unittest.TestCase):
    def test_single_superscript_with_twin(self):
        self.assertEqual(_expand_collapsed(861, "", 330, {"ст.86-1"}), "ст.86-1")
        self.assertEqual(_expand_collapsed(1321, "", 330, {"ст.132-1"}), "ст.132-1")

    def test_two_digit_superscript(self):
        self.assertEqual(_expand_collapsed(16310, "", 330, {"ст.163-10"}), "ст.163-10")

    def test_compound_superscript(self):
        # ст.1729-1 → ст.172-9-1 (superscript inside a compound number).
        self.assertEqual(_expand_collapsed(1729, "-1", 330, set()), "ст.172-9-1")

    def test_no_twin_not_expanded(self):
        self.assertIsNone(_expand_collapsed(999, "", 330, set()))


class Reconcile(unittest.TestCase):
    def test_cross_edition_reconcile(self):
        # edition A carries ст.86-1 (base present); edition B has it collapsed as ст.861.
        edA = _arts(["ст.85", "ст.86-1", "ст.87"])
        edB = _arts(["ст.85", "ст.861", "ст.87"])
        eds = [("A", edA), ("B", edB)]
        known = {u.path for _e, us in eds for u in us}
        n = reconcile_collapsed(eds, genuine_max(known), known)
        self.assertEqual(n, 1)
        self.assertEqual([u.path for u in edB], ["ст.85", "ст.86-1", "ст.87"])


class ReconcilePoint(unittest.TestCase):
    # cross-edition twin set: article 121-4 with a hyphenated point family (п.10-1..10-14, no 13).
    KNOWN = {"ст.121-4", "ст.121-4/п.10"} | {f"ст.121-4/п.10-{i}" for i in (1, 2, 3, 11, 12, 14)}

    def test_prefix_and_point_disambiguated(self):
        # ст.1214/п.101 → ст.121-4/п.10-1 (collapsed article prefix AND collapsed point number).
        self.assertEqual(_reconcile_point("ст.1214/п.101", 121, self.KNOWN), "ст.121-4/п.10-1")

    def test_two_digit_point_superscript(self):
        self.assertEqual(_reconcile_point("ст.1214/п.1011", 121, self.KNOWN), "ст.121-4/п.10-11")

    def test_family_bracket_fallback(self):
        # п.1013 has no exact twin (п.10-13 absent) but is bracketed by the п.10-* family → п.10-13.
        self.assertEqual(_reconcile_point("ст.1214/п.1013", 121, self.KNOWN), "ст.121-4/п.10-13")

    def test_prefix_only_when_point_genuine(self):
        # a genuine point (п.1) under a collapsed article prefix → only the prefix is fixed.
        self.assertEqual(_reconcile_point("ст.1214/п.10", 121, self.KNOWN), "ст.121-4/п.10")

    def test_no_change_when_already_correct(self):
        self.assertIsNone(_reconcile_point("ст.121-4/п.10-1", 121, self.KNOWN))


if __name__ == "__main__":
    unittest.main(verbosity=2)
