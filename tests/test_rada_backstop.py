"""Unit tests: the Rada datred/edcnt backstop logic (card_state, compare, gate).

    uv run python tests/test_rada_backstop.py
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.freshness import rada_backstop as bs  # noqa: E402


class CardState(unittest.TestCase):
    def test_counts_and_latest(self):
        card = {"eds": [{"datred": 20240101}, {"datred": "20260624"}, {"datred": 20250601}]}
        self.assertEqual(bs.card_state(card), (3, "20260624"))

    def test_ignores_malformed_datred(self):
        card = {"eds": [{"datred": 20240101}, {"datred": None}, {"datred": "bad"}, {"datred": 999}]}
        self.assertEqual(bs.card_state(card), (1, "20240101"))

    def test_empty(self):
        self.assertEqual(bs.card_state({"eds": []}), (0, None))
        self.assertEqual(bs.card_state({}), (0, None))

    def test_dedups_repeated_datred(self):
        # a card that lists the same datred twice stores ONE edition (UNIQUE key) — so
        # card_state must not count it twice (otherwise edcnt_card is falsely inflated).
        card = {"eds": [{"datred": 20240101}, {"datred": "20240101"}, {"datred": 20260624}]}
        self.assertEqual(bs.card_state(card), (2, "20260624"))

    def test_rejects_impossible_date(self):
        # 20260230 is 8 digits & isdigit() but not a real calendar date -> dropped,
        # matching fetch_cards.edition_date() (the old len==8 check counted it -> false +1).
        card = {"eds": [{"datred": 20240101}, {"datred": 20260230}]}
        self.assertEqual(bs.card_state(card), (1, "20240101"))


class Compare(unittest.TestCase):
    def test_consistent(self):
        card = {"eds": [{"datred": 20240101}, {"datred": 20260624}]}
        r = bs.compare("4695-20", card, (2, "20260624"))
        self.assertFalse(r["mismatch"])

    def test_new_edition_on_rada(self):
        # Rada card has a newer edition we don't have yet -> mismatch (would be missed
        # by the r.txt presence signal if the probe skipped that day).
        card = {"eds": [{"datred": 20240101}, {"datred": 20260624}, {"datred": 20260701}]}
        r = bs.compare("3633-20", card, (2, "20260624"))
        self.assertTrue(r["mismatch"])
        self.assertEqual((r["edcnt_card"], r["edcnt_db"]), (3, 2))

    def test_newer_datred_same_count(self):
        card = {"eds": [{"datred": 20240101}, {"datred": 20260702}]}
        r = bs.compare("x", card, (2, "20260624"))
        self.assertTrue(r["mismatch"])


class Gate(unittest.TestCase):
    def test_rada_changed_forces_run(self):
        # rada_changed short-circuits before any DB lookup.
        self.assertTrue(bs.should_run(conn=None, rada_changed=True))

    def test_no_prior_run_runs(self):
        with mock.patch.object(bs, "_last_run_at", lambda conn: None):
            self.assertTrue(bs.should_run(conn=None, rada_changed=False))

    def test_recent_run_skips(self):
        now = datetime(2026, 7, 8, tzinfo=timezone.utc)
        with mock.patch.object(bs, "_last_run_at", lambda conn: now - timedelta(days=3)):
            self.assertFalse(bs.should_run(conn=None, rada_changed=False, now=now, n_days=7))

    def test_stale_run_runs(self):
        now = datetime(2026, 7, 8, tzinfo=timezone.utc)
        with mock.patch.object(bs, "_last_run_at", lambda conn: now - timedelta(days=8)):
            self.assertTrue(bs.should_run(conn=None, rada_changed=False, now=now, n_days=7))


class _Cur:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _Conn:
    """Offline stand-in: run() writes source_checks + reads via mocked helpers."""

    def cursor(self):
        return _Cur()

    def commit(self):
        pass


class RunSignal(unittest.TestCase):
    """A partial/all-error run must NOT emit a false "changed" verdict nor a baseline signal
    (both write signal_value=NULL, which also keeps _last_run_at from resetting the gate)."""

    def _run(self, fetch):
        # bs._register was removed (source_registry is written by the single writer
        # probe._upsert_sources via sources.py 'rada-backstop'), so it is not mocked here.
        with mock.patch.object(bs, "_last_signal", lambda conn: "PRIOR_BASELINE_SIG"), \
             mock.patch.object(bs, "db_state", lambda conn, nreg: (0, None)), \
             mock.patch.object(bs.budget, "can_spend", lambda n: True), \
             mock.patch.object(bs.budget, "add", lambda n: None):
            return bs.run(_Conn(), rada_changed=True, fetch=fetch)

    def test_complete_run_sets_signal(self):
        # every seed act fetched -> complete -> real signal (comparable baseline).
        res = self._run(lambda url: {"eds": [{"datred": 20240101}]})
        self.assertTrue(res["complete"])
        self.assertIsNotNone(res["signal"])

    def test_partial_run_signal_none_no_change(self):
        # first act fetched, the rest raise (budget/HTTP) -> partial.
        calls = {"n": 0}

        def fetch(url):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"eds": [{"datred": 20240101}]}
            raise RuntimeError("budget/HTTP boom")
        res = self._run(fetch)
        self.assertFalse(res["complete"])
        self.assertIsNone(res["signal"])   # NULL -> no baseline poison, gate not reset
        self.assertFalse(res["changed"])   # no false "changed" vs the prior baseline

    def test_all_error_run_signal_none(self):
        res = self._run(lambda url: (_ for _ in ()).throw(RuntimeError("all boom")))
        self.assertEqual(res["results"], [])
        self.assertIsNone(res["signal"])
        self.assertFalse(res["changed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
