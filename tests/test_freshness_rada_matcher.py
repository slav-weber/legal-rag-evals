"""Self-test: the Rada act-aware freshness matcher must catch seed acts by
their CANONICAL nreg (3633-IX == 3633-20) and survive the cyrillic 'п' in nregs.

Runs with stdlib unittest (no pytest):
    uv run python tests/test_freshness_rada_matcher.py

Proves that a production "seed acts in feed: none" is an honest true-negative:
the matcher demonstrably fires on a saved sample that contains seeds.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.freshness.probe import _decode_rada, seed_hits  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rada_r_sample.txt"

# alias -> canonical, as seed_alias_map(conn) would build it from card_json.nreg.
# The 3633 pair is the whole point: the feed uses 3633-20, our seed key is 3633-IX.
ALIAS_MAP = {
    "3633-IX": "3633-20", "3633-20": "3633-20",
    "560-2024-п": "560-2024-п",
    "76-2023-п": "76-2023-п",  # seed re-keyed 76-2024-п → 76-2023-п (card nreg == key, no alias)
    "1404-19": "1404-19",
}


class _FakeResp:
    def __init__(self, content: bytes, content_type: str = ""):
        self.content = content
        self.headers = {"content-type": content_type} if content_type else {}


class SeedMatcher(unittest.TestCase):
    def setUp(self):
        self.text = FIXTURE.read_text(encoding="utf-8")

    def test_canonical_mobilisation_law_is_found(self):
        # 3633-20 present in feed -> caught via the canonical alias (a key-only matcher is blind).
        self.assertIn("3633-20", seed_hits(self.text, ALIAS_MAP))

    def test_cyrillic_p_nreg_is_found(self):
        self.assertIn("560-2024-п", seed_hits(self.text, ALIAS_MAP))

    def test_absent_seed_not_reported(self):
        # 76-2023-п is not in the fixture -> honest absence.
        self.assertNotIn("76-2023-п", seed_hits(self.text, ALIAS_MAP))

    def test_full_hit_set_is_exact(self):
        self.assertEqual(seed_hits(self.text, ALIAS_MAP), ["3633-20", "560-2024-п"])

    def test_old_spelling_maps_to_canonical(self):
        # If the feed ever used the old "3633-IX" spelling, it still maps to 3633-20.
        self.assertEqual(seed_hits("... 3633-IX ...", ALIAS_MAP), ["3633-20"])

    def test_token_boundary_trap(self):
        # 13633-20 must NOT satisfy 3633-20 (left boundary), so a "none" is honest.
        self.assertEqual(seed_hits("row 13633-20 only", ALIAS_MAP), [])

    def test_true_none(self):
        self.assertEqual(seed_hits("nothing relevant here 111-11", ALIAS_MAP), [])


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Minimal offline stand-in for a psycopg connection (no DB, no network)."""

    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)


class SeedAliasMapOffline(unittest.TestCase):
    """seed_alias_map() builds alias->canonical from card_json, offline."""

    def test_builds_both_spellings(self):
        from pipelines.freshness.probe import seed_alias_map
        rows = [("3633-IX", "3633-20"), ("560-2024-п", "560-2024-п"),
                ("76-2023-п", "76-2023-п")]
        amap = seed_alias_map(_FakeConn(rows))
        # the mobilisation law's canonical (feed uses 3633-20) is captured under both keys
        self.assertEqual(amap["3633-IX"], "3633-20")
        self.assertEqual(amap["3633-20"], "3633-20")
        # cyrillic-'п' postanova maps to itself (card nreg == key)
        self.assertEqual(amap["76-2023-п"], "76-2023-п")
        # every seed key is present as its own alias even if its card wasn't returned
        for key in ("3543-12", "1404-19"):
            self.assertEqual(amap[key], key)


class RadaDecode(unittest.TestCase):
    SAMPLE = "560-2024-п мобілізація"

    def test_utf8(self):
        self.assertEqual(_decode_rada(_FakeResp(self.SAMPLE.encode("utf-8"))), self.SAMPLE)

    def test_windows1251_fallback(self):
        # A win-1251-encoded body (no charset header) must still decode 'п' correctly.
        self.assertEqual(
            _decode_rada(_FakeResp(self.SAMPLE.encode("windows-1251"))), self.SAMPLE)

    def test_explicit_charset_header_honored(self):
        self.assertEqual(
            _decode_rada(_FakeResp(self.SAMPLE.encode("windows-1251"),
                                   "text/plain; charset=windows-1251")),
            self.SAMPLE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
