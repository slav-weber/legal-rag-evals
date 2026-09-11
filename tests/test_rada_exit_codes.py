"""Exit codes that cron and the orchestrator read: a failure is never reported as a success or as a
planned skip. The Rada reachability watcher, the card fetch and the retrieval-baseline regression
check, each driven through main() with the network and the database replaced by fakes.

    uv run python -m unittest discover -s tests -p test_rada_exit_codes.py -q
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval import retrieval_baseline as RB  # noqa: E402
from pipelines import exitcodes  # noqa: E402
from pipelines.rada import fetch_cards, reachability  # noqa: E402


class _Cursor:
    """Answers the two count queries fetch_cards runs at the end; every other statement is a no-op."""

    def __init__(self, counts: dict):
        self._counts = counts
        self._last = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._last = sql

    def fetchone(self):
        return (self._counts["editions"] if "editions" in self._last else self._counts["acts"],)


class _Conn:
    def __init__(self, counts: dict):
        self._counts = counts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _Cursor(self._counts)

    def commit(self):
        pass


class Reachability(unittest.TestCase):
    def _main_with(self, signal: str) -> int:
        with mock.patch.object(reachability, "probe", return_value=(signal, "stub")), \
             mock.patch("pipelines.db.run_migrations", side_effect=RuntimeError("no database")), \
             redirect_stdout(io.StringIO()):
            return reachability.main()

    def test_red_is_a_failure_not_a_planned_skip(self):
        self.assertEqual(self._main_with(reachability.RED), exitcodes.FAIL)

    def test_other_signals_keep_their_codes(self):
        self.assertEqual(self._main_with(reachability.GREEN), exitcodes.OK)
        self.assertEqual(self._main_with(reachability.YELLOW), exitcodes.SKIP)
        self.assertEqual(self._main_with(reachability.ERROR), exitcodes.SKIP)


class FetchCards(unittest.TestCase):
    CARD = {"nazva": "Акт", "typ": 1, "eds": [{"datred": 20240101, "pidstava": "p", "size": 1}]}

    def _main(self, acts: list[str], editions_in_db: int = 150) -> int:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        def fake_get_json(url):
            if "BROKEN" in url:
                raise RuntimeError("HTTP 500")
            return dict(self.CARD)

        with mock.patch.object(sys, "argv", ["fetch_cards", "--acts", *acts]), \
             mock.patch("pipelines.orchestration.warn_if_standalone"), \
             mock.patch.object(fetch_cards, "run_migrations"), \
             mock.patch.object(fetch_cards, "connect",
                               return_value=_Conn({"acts": len(acts), "editions": editions_in_db})), \
             mock.patch.object(fetch_cards, "get_json", side_effect=fake_get_json), \
             mock.patch.object(fetch_cards, "RAW_DIR", tmp), \
             mock.patch.object(fetch_cards.budget, "can_spend", return_value=True), \
             mock.patch.object(fetch_cards.budget, "add"), \
             mock.patch.object(fetch_cards.budget, "remaining", return_value=100_000_000), \
             mock.patch.object(fetch_cards._summary, "emit"), \
             redirect_stdout(io.StringIO()):
            return fetch_cards.main()

    def test_a_failed_card_fails_the_run_even_above_the_floor(self):
        self.assertEqual(self._main(["OK-1", "BROKEN-1"]), exitcodes.FAIL)

    def test_all_cards_fetched_above_the_floor_is_ok(self):
        self.assertEqual(self._main(["OK-1"]), exitcodes.OK)

    def test_below_the_floor_fails(self):
        self.assertEqual(self._main(["OK-1"], editions_in_db=10), exitcodes.FAIL)


class RetrievalBaseline(unittest.TestCase):
    def _compare(self, live_hits: list[dict]) -> int:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        base = tmp / "baseline.jsonl"
        base.write_text(
            json.dumps({"kind": "retrieval-baseline", "n": 1, "k": 10,
                        "corpus": {"chunks": 1, "acts": 1}}) + "\n"
            + json.dumps({"id": 1, "class": "citation", "gold_rank": 1}) + "\n",
            encoding="utf-8")
        gold = [{"id": 1, "question": "q", "as_of": None, "class": "citation",
                 "expected": [("A", "ст.1")]}]
        with mock.patch.object(RB, "connect", return_value=_Conn({"acts": 1, "editions": 0})), \
             mock.patch.object(RB, "_known_acts", return_value={"A"}), \
             mock.patch.object(RB, "_load_gold", return_value=gold), \
             mock.patch.object(RB, "_corpus_shape", return_value={"chunks": 1, "acts": 1}), \
             mock.patch.object(RB, "probe", return_value=(live_hits, {})), \
             redirect_stdout(io.StringIO()):
            return RB.compare(base, Path("gold.jsonl"))

    def test_a_lost_gold_hit_fails_the_check(self):
        self.assertEqual(self._compare([{"rank": 1, "act": "B", "stem": "ст.9"}]), 1)

    def test_a_kept_gold_hit_passes(self):
        self.assertEqual(self._compare([{"rank": 1, "act": "A", "stem": "ст.1"}]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
