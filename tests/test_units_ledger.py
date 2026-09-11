"""Unit tests: the units-ledger diff catches deletion/injection the floors miss.

    uv run python tests/test_units_ledger.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.units_ledger import diff  # noqa: E402


class LedgerDiff(unittest.TestCase):
    LEDGER = {"КАС|2026-01-01": 2329, "3543-12|2026-07-31": 112, "1404-19|2030-01-01": 33}

    def test_intact(self):
        d = diff(self.LEDGER, dict(self.LEDGER))
        self.assertEqual(d["changed_or_deleted"], {})
        self.assertEqual(d["new_editions"], [])

    def test_partial_deletion_detected(self):
        # one edition lost units but total still above any floor -> must be caught
        live = dict(self.LEDGER)
        live["КАС|2026-01-01"] = 2000
        d = diff(self.LEDGER, live)
        self.assertIn("КАС|2026-01-01", d["changed_or_deleted"])
        self.assertEqual(d["changed_or_deleted"]["КАС|2026-01-01"], {"ledger": 2329, "db": 2000})

    def test_edition_vanished_detected(self):
        live = dict(self.LEDGER)
        del live["3543-12|2026-07-31"]
        d = diff(self.LEDGER, live)
        self.assertIn("3543-12|2026-07-31", d["changed_or_deleted"])
        self.assertIsNone(d["changed_or_deleted"]["3543-12|2026-07-31"]["db"])

    def test_new_edition_is_growth_not_failure(self):
        live = dict(self.LEDGER)
        live["3633-20|2026-08-01"] = 50
        d = diff(self.LEDGER, live)
        self.assertEqual(d["changed_or_deleted"], {})
        self.assertEqual(d["new_editions"], ["3633-20|2026-08-01"])

    def test_growth_inside_a_known_edition_detected(self):
        # an injection into a known edition (a reparse that turns quoted amendment headings into
        # phantom host articles) keeps every floor green; the ledger is an exact manifest, so a
        # single extra unit is a count drift exactly like a missing one
        live = dict(self.LEDGER)
        live["3543-12|2026-07-31"] = 113
        d = diff(self.LEDGER, live)
        self.assertEqual(d["changed_or_deleted"],
                         {"3543-12|2026-07-31": {"ledger": 112, "db": 113}})
        self.assertEqual(d["new_editions"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
