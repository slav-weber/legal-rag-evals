"""The Rada byte budget: the daily self-cap stays under the source's published limit, and add()
accumulates under the cross-process lock (msvcrt on Windows, flock elsewhere).

    uv run python -m unittest discover -s tests -p test_rada_budget.py -q
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.rada import budget  # noqa: E402

PUBLISHED_DAILY_LIMIT = 200_000_000          # data.rada.gov.ua open data: 200 MB a day


class Cap(unittest.TestCase):
    def test_self_cap_stays_under_the_published_limit(self):
        self.assertLessEqual(budget.CAP_BYTES, PUBLISHED_DAILY_LIMIT)
        self.assertEqual(budget.CAP_BYTES, 180_000_000)          # the chosen self-cap, decimal MB


class Accounting(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        rada, ksu = self.tmp / "rada", self.tmp / "ksu"
        for name, value in (("RADA_DIR", rada), ("KSU_DIR", ksu),
                            ("_TRAFFIC_DIR", rada / ".traffic"), ("_BUDGET_DIRS", (rada, ksu))):
            patcher = mock.patch.object(budget, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_add_accumulates_under_the_lock(self):
        budget.add(1_000)
        budget.add(2_500)
        self.assertEqual(budget.used(), 3_500)
        self.assertEqual(budget.remaining(), budget.CAP_BYTES - 3_500)

    def test_can_spend_refuses_past_the_cap(self):
        budget.add(budget.CAP_BYTES - 100)
        self.assertTrue(budget.can_spend(100))
        self.assertFalse(budget.can_spend(101))


if __name__ == "__main__":
    unittest.main(verbosity=2)
