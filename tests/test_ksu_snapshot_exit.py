"""Smoke: pipelines/ksu/snapshot.py must exit non-zero on fetch failures.

Runs with the stdlib unittest (no pytest dependency):
    uv run python tests/test_ksu_snapshot_exit.py
    uv run python -m unittest tests.test_ksu_snapshot_exit

The integration smoke injects a fake fetcher (HTTP 500 / raising) and a no-op DB/
budget so no network or Postgres is touched, then asserts main() returns 1 — the
"artificial HTTP fail -> exit != 0" case the spec requires.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.ksu import snapshot  # noqa: E402


class _FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.content = text.encode("utf-8")
        self.encoding = "utf-8"
        self.text = text


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):  # not reached on the 500/raise path (already_done patched)
        raise AssertionError("cursor should not be used on the failure path")

    def commit(self):
        pass


class _FakeBudget:
    CAP_BYTES = 180 * 1024 * 1024

    def used(self):
        return 0

    def remaining(self):
        return 10**9

    def can_spend(self, n):
        return True

    def add(self, n):
        pass


class ExitCodeUnit(unittest.TestCase):
    def test_clean_run_is_zero(self):
        self.assertEqual(snapshot.exit_code([], []), 0)

    def test_errors_are_nonzero(self):
        self.assertEqual(snapshot.exit_code(["v002p710-15: HTTP 500"], []), 1)

    def test_bad_char_is_nonzero(self):
        self.assertEqual(snapshot.exit_code([], ["v003p710-12"]), 1)


class MainFailurePathSmoke(unittest.TestCase):
    def _run_with_fetcher(self, fetcher) -> int:
        with mock.patch.object(snapshot, "NREGS", ["v002p710-15"]), \
             mock.patch.object(snapshot, "already_done", lambda conn, nreg: False), \
             mock.patch.object(snapshot, "get", fetcher), \
             mock.patch.object(snapshot, "connect", lambda: _FakeConn()), \
             mock.patch.object(snapshot, "budget", _FakeBudget()):
            return snapshot.main()

    def test_http_500_exits_nonzero(self):
        code = self._run_with_fetcher(lambda url, ua=None: _FakeResp(500))
        self.assertEqual(code, 1)

    def test_network_exception_exits_nonzero(self):
        def boom(url, ua=None):
            raise RuntimeError("connection reset")
        code = self._run_with_fetcher(boom)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
