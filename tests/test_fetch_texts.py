"""Politeness is enforced, not advisory: every edition request fetch_texts sends to Rada waits the
polite pause first. The daily byte budget meters bytes, not request rate, so it is no substitute:
without the pause the downloads go out back to back, far above the host's published per-minute
terms, which is the traffic that earns the collector's IP an anti-DDoS block. The HTTP layer, the
pause, the database and the budget are faked: nothing sleeps and nothing leaves the machine.

    uv run python -m unittest discover -s tests -p test_fetch_texts.py -q
"""

from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines import exitcodes  # noqa: E402
from pipelines.checks import _common  # noqa: E402
from pipelines.rada import fetch_texts as FT  # noqa: E402


class _Response:
    """The fields fetch_txt and _common.get read from an httpx.Response."""

    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.encoding = None
        self.is_redirect = False
        self.headers: dict = {}


class _Wire:
    """The HTTP layer and the polite pause, logged on one timeline."""

    def __init__(self, statuses=()):
        self.events: list[str] = []
        self._statuses = list(statuses)

    def pause(self):
        self.events.append("pause")

    def get(self, url, **kw):
        self.events.append("request")
        status = self._statuses.pop(0) if self._statuses else 200
        return _Response(status, "Стаття 1. Текст редакції." if status == 200 else "")


class _Cursor:
    """Answers the edition query with the given (edition_date, size) rows and accepts the
    txt_path updates."""

    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _Cursor(self._rows)

    def commit(self):
        pass


class _Budget:
    """A Rada byte budget with room to spare: nothing is deferred."""

    CAP_BYTES = 180_000_000

    def used(self):
        return 0

    def remaining(self):
        return self.CAP_BYTES

    def can_spend(self, nbytes=0):
        return True

    def add(self, nbytes):
        pass


class PolitePause(unittest.TestCase):
    EDITIONS = [(date(2024, 1, 1), 1000), (date(2025, 1, 1), 1000), (date(2026, 1, 1), 1000)]

    def test_every_edition_request_waits_the_polite_pause(self):
        wire = _Wire()
        txt_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, txt_dir, ignore_errors=True)
        with mock.patch.object(sys, "argv", ["fetch_texts", "--acts", "TEST-1"]), \
             mock.patch("pipelines.orchestration.warn_if_standalone"), \
             mock.patch.object(FT, "connect", return_value=_Conn(self.EDITIONS)), \
             mock.patch.object(FT, "budget", _Budget()), \
             mock.patch.object(FT, "TXT_DIR", txt_dir), \
             mock.patch.object(FT, "rel", lambda path: path.name), \
             mock.patch.object(_common, "polite_sleep", wire.pause), \
             mock.patch.object(_common.httpx, "get", wire.get), \
             redirect_stdout(io.StringIO()):
            code = FT.main()
        self.assertEqual(code, exitcodes.OK)
        self.assertEqual(len(list((txt_dir / "TEST-1").glob("ed*.txt"))), 3)   # all fetched
        self.assertEqual(wire.events, ["pause", "request"] * 3)    # one pause before each

    def test_a_retried_request_waits_the_polite_pause_too(self):
        wire = _Wire(statuses=[503, 200])
        backoff = SimpleNamespace(sleep=lambda seconds: wire.events.append("backoff"))
        with mock.patch.object(_common, "polite_sleep", wire.pause), \
             mock.patch.object(_common.httpx, "get", wire.get), \
             mock.patch.object(FT, "time", backoff), \
             redirect_stdout(io.StringIO()):
            text, _nbytes = FT.fetch_txt("TEST-1", "20260101")
        self.assertIsNotNone(text)
        self.assertEqual(wire.events, ["pause", "request", "backoff", "pause", "request"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
