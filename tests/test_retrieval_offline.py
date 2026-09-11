"""Offline tests for the pure parts of the retriever: the scope clause, reciprocal-rank fusion under
the calibrated weights, symmetric channel degradation, the reranker's honest fallback, the
exact-lookup route (article parsing, act binding, round-robin) and query normalisation.

The live retrieval eval measures recall on the private corpus and cannot run in CI. These tests pin
the logic that decides what reaches the candidate set, with the database, LM Studio and the
reranker replaced by fakes.

    uv run python -m unittest discover -s tests -p test_retrieval_offline.py -q
"""

from __future__ import annotations

import inspect
import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.rag import retrieval as R  # noqa: E402


def _hit(act: str, path: str, **extra) -> dict:
    return {"act": act, "unit_path": path, "in_force_from": "2020-01-01", "citation": path,
            "content_hash": f"{act}:{path}", **extra}


class _FakeCursor:
    """Answers the exact-lookup query from a {article: rows} map, keyed by the %(art)s param."""

    def __init__(self, rows: dict):
        self._rows = rows
        self._last: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self._last = self._rows.get(params["art"], [])

    def fetchall(self):
        return list(self._last)


class _FakeConn:
    def __init__(self, rows: dict):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)


class ScopeClause(unittest.TestCase):
    """An edition is in force on as_of when it started on or before that day and has not ended
    before it: the last day in force still counts."""

    def test_both_bounds_are_inclusive(self):
        clause = R.scope_clause("ci")
        self.assertIn("ci.in_force_from <= COALESCE(%(as_of)s::date", clause)
        self.assertIn("ci.in_force_to IS NULL OR ci.in_force_to >= COALESCE(%(as_of)s::date",
                      clause)


class Fusion(unittest.TestCase):
    """RRF: score = sum of w_c / (k + rank_c); the calibrated weights are part of the ranking."""

    def test_calibrated_canon_is_the_default(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("RRF_")}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertEqual(R._weights(), {"dense": 2.0, "fts": 0.5, "lemma": 0.5})

    def test_weights_decide_the_order(self):
        # A at rank 1 in dense alone, B at rank 1 in both keyword channels: under the calibrated
        # weights (2.0 / 0.5 / 0.5) A wins; under equal weights B would.
        fused = R._rrf({"dense": [_hit("A", "ст.1")], "fts": [_hit("B", "ст.2")],
                        "lemma": [_hit("B", "ст.2")]},
                       {"dense": 2.0, "fts": 0.5, "lemma": 0.5}, 60)
        self.assertEqual([h["act"] for h in fused], ["A", "B"])

    def test_fusion_records_channels_and_drops_channel_scores(self):
        fused = R._rrf({"dense": [_hit("A", "ст.1", dist=0.1)],
                        "fts": [_hit("A", "ст.1", rank=3.0)]},
                       {"dense": 2.0, "fts": 0.5}, 60)
        self.assertEqual(fused[0]["channels"], {"dense": 1, "fts": 1})
        self.assertNotIn("dist", fused[0])                 # channel-local scores mean nothing
        self.assertNotIn("rank", fused[0])                 # after fusion


class Degradation(unittest.TestCase):
    """A lost channel or a lost reranker degrades the result loudly, never silently."""

    def test_failed_channel_is_flagged_and_the_survivors_fuse(self):
        conn = mock.Mock()
        with mock.patch.object(R, "dense", side_effect=RuntimeError("LM Studio down")), \
             mock.patch.object(R, "fts", return_value=[_hit("A", "ст.1")]), \
             mock.patch.object(R, "lemma", return_value=[_hit("A", "ст.1")]):
            fused, meta = R.hybrid(conn, "q")
        self.assertEqual(meta["degraded"], ["dense"])
        self.assertEqual(meta["channels_run"], ["fts", "lemma"])
        self.assertEqual([h["act"] for h in fused], ["A"])
        conn.rollback.assert_called()              # the aborted transaction is cleared for the rest

    def test_reranker_outage_is_flagged_not_passed_off_as_reranked(self):
        from ml.reranker import RerankerUnavailable
        fused = [_hit("A", "ст.1"), _hit("B", "ст.2")]
        with mock.patch.object(R, "exact_lookup", return_value=[]), \
             mock.patch.object(R, "hybrid", return_value=(fused, {"degraded": []})), \
             mock.patch.object(R, "_fetch_texts", return_value={}), \
             mock.patch("ml.reranker.rerank", side_effect=RerankerUnavailable("no GPU")):
            hits, meta = R.search(None, "q", k=2)
        self.assertFalse(meta["reranked"])
        self.assertIn("reranker", meta["degraded"])
        self.assertEqual([h["act"] for h in hits], ["A", "B"])       # RRF order kept, and flagged


class Reranking(unittest.TestCase):
    def test_reranked_order_is_best_first(self):
        fused = [_hit("A", "ст.1"), _hit("B", "ст.2")]
        with mock.patch.object(R, "exact_lookup", return_value=[]), \
             mock.patch.object(R, "hybrid", return_value=(fused, {"degraded": []})), \
             mock.patch.object(R, "_fetch_texts", return_value={}), \
             mock.patch("ml.reranker.rerank", return_value=[0.1, 0.9]):
            hits, meta = R.search(None, "q", k=2)
        self.assertTrue(meta["reranked"])
        self.assertEqual([h["act"] for h in hits], ["B", "A"])       # the higher score comes first


class ExactRoute(unittest.TestCase):
    """«Article N of act X» resolves by regex and SQL, never by similarity."""

    def setUp(self):
        patcher = mock.patch.object(R, "_TITLE_KEYS_CACHE", [])      # abbreviations only, no DB
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_article_suffix_is_part_of_the_number(self):
        self.assertEqual(R._parse_article("Що передбачає стаття 210-1 КУпАП?"), "ст.210-1")
        self.assertEqual(R._parse_article("ст. 173-2 КУпАП"), "ст.173-2")

    def test_code_abbreviations_are_case_sensitive(self):
        # «КАС» is the Code of Administrative Procedure; «кас» (genitive plural of «каса», a cash
        # desk) is an ordinary word and must not route a question to the code.
        mentions = R._act_mentions(None, "Що передбачає ст. 47 КАС?")
        self.assertEqual({nreg for _pos, nreg in mentions}, {"2747-15"})
        self.assertEqual(R._act_mentions(None, "Графік роботи кас у вихідні дні"), [])

    def test_each_article_binds_to_the_act_on_its_right(self):
        self.assertEqual(R._citations(None, "ст.47 КАС і ст.210 КУпАП"),
                         [("2747-15", "ст.47"), ("8073-10", "ст.210")])

    def test_an_article_without_its_own_act_is_dropped_not_guessed(self):
        # two acts named, the second unrecognised: ст.15 must not be served from КАС
        self.assertEqual(R._citations(None, "ст.47 КАС і ст.15 закону про рибальство"),
                         [("2747-15", "ст.47")])

    def test_round_robin_keeps_a_small_article_in_the_top(self):
        # ст.47 has nine parts, ст.210 one: interleaving must not let ст.47 starve ст.210
        rows = {"ст.47": [(f"h{i}", "2747-15", f"ст.47/ч.{i}", "c", "2020-01-01", None)
                          for i in range(9, 0, -1)],
                "ст.210": [("h210", "8073-10", "ст.210", "c", "2020-01-01", None)]}
        hits = R.exact_lookup(_FakeConn(rows), "ст.47 КАС і ст.210 КУпАП", limit=3)
        self.assertEqual([h["unit_path"] for h in hits], ["ст.47/ч.1", "ст.210", "ст.47/ч.2"])
        self.assertTrue(all(h["route"] == "exact" for h in hits))


def _channel_recorder(name: str, seen: dict):
    """A stand-in for one candidate channel. It records the as_of the real channel would receive,
    bound against the real signature, so a date the caller drops reads as the default None (which
    the scope clause turns into today's Kyiv date), and it finds nothing."""
    signature = inspect.signature(getattr(R, name))

    def channel(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        seen[name] = bound.arguments["as_of"]
        return []
    return channel


class _AsOfConn:
    """Records the as_of of every exact-route query; the cited article has no rows."""

    def __init__(self):
        self.as_of: list = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.as_of.append(params["as_of"])

    def fetchall(self):
        return []

    def rollback(self):
        pass


class AsOfReachesEveryChannel(unittest.TestCase):
    """Only editions in force on as_of are served, and the scope gate runs inside each channel, so
    the requested date has to reach every one of them. A channel called without it falls back to
    today: a question about an earlier date would be answered from the editions in force today."""

    AS_OF = "2019-05-01"

    def setUp(self):
        patcher = mock.patch.object(R, "_TITLE_KEYS_CACHE", [])      # abbreviations only, no DB
        patcher.start()
        self.addCleanup(patcher.stop)

    def _channels(self, seen: dict) -> ExitStack:
        stack = ExitStack()
        for name in R.CHANNELS:
            stack.enter_context(mock.patch.object(R, name, _channel_recorder(name, seen)))
        return stack

    def test_hybrid_gates_every_channel_on_the_requested_date(self):
        seen: dict = {}
        with self._channels(seen):
            _fused, meta = R.hybrid(mock.Mock(), "строк оскарження постанови", as_of=self.AS_OF)
        self.assertEqual(meta["degraded"], [])                       # every channel ran
        self.assertEqual(seen, {name: self.AS_OF for name in R.CHANNELS})

    def test_search_gates_every_route_on_the_requested_date(self):
        seen: dict = {}
        conn = _AsOfConn()
        with self._channels(seen):
            R.search(conn, "Що передбачає ст. 47 КАС?", as_of=self.AS_OF, k=5)
        self.assertEqual(seen, {name: self.AS_OF for name in R.CHANNELS})
        self.assertEqual(conn.as_of, [self.AS_OF])                   # and the exact route


class Normalisation(unittest.TestCase):
    def test_apostrophe_variants_fold_to_one(self):
        plain = R._norm("обов'язок")
        for variant in ("обовʼязок", "обов’язок", "обов`язок"):
            self.assertEqual(R._norm(variant), plain, variant)

    def test_quotes_dropped_and_whitespace_collapsed(self):
        self.assertEqual(R._norm("  Закон «Про  оборону» "), "закон про оборону")

    def test_natural_order_of_parts(self):
        self.assertEqual(sorted(["ст.5/п.10", "ст.5/п.2", "ст.5"], key=R.natkey),
                         ["ст.5", "ст.5/п.2", "ст.5/п.10"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
