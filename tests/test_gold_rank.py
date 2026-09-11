"""Gold matching in the retrieval eval: a hit counts when it is the expected article or a part of
it, never a different article that merely shares a prefix (ст.21 is not ст.210).

    uv run python -m unittest discover -s tests -p test_gold_rank.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.retrieval_eval import _gold_rank  # noqa: E402


def _h(act: str, path: str) -> dict:
    return {"act": act, "unit_path": path}


class GoldRank(unittest.TestCase):
    def test_the_article_and_its_parts_match(self):
        self.assertEqual(_gold_rank([_h("A", "ст.21")], [("A", "ст.21")]), 1)
        self.assertEqual(_gold_rank([_h("A", "ст.5"), _h("A", "ст.21/ч.2")], [("A", "ст.21")]), 2)

    def test_a_longer_number_is_a_different_article(self):
        self.assertIsNone(_gold_rank([_h("A", "ст.210"), _h("A", "ст.21-1")], [("A", "ст.21")]))

    def test_the_act_must_match_too(self):
        self.assertIsNone(_gold_rank([_h("B", "ст.21")], [("A", "ст.21")]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
