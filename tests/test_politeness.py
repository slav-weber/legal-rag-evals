"""Pin tests: per-host politeness policy + caps + cross-process single-flight (Windows msvcrt).

    uv run python tests/test_politeness.py
"""

from __future__ import annotations

import datetime
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines import politeness as P  # noqa: E402

# The state lock is a Windows-native msvcrt lock (no POSIX branch), so every test that takes
# it skips on other platforms instead of erroring on `import msvcrt`.
_WINDOWS_LOCK = unittest.skipUnless(sys.platform == "win32",
                                    "pipelines.politeness uses a Windows-native msvcrt lock")


class Politeness(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_dir = P._DIR
        P._DIR = self.tmp

    def tearDown(self):
        P._DIR = self._orig_dir
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k in ("ZZ-P", "ZZ-C", "ZZ-B", "ZZ-BC"):
            P.POLICIES.pop(k, None)

    def test_policy_table_per_host(self):
        # per-host, NOT one-size: rada strict pause, od.reyestr light pause (0.2 s),
        # unknown → conservative default.
        self.assertEqual(P.policy("data.rada.gov.ua")["pause_s"], 6.0)
        self.assertEqual(P.policy("od.reyestr.court.gov.ua")["pause_s"], 0.2)
        self.assertEqual(P.policy("unknown.example.com"), P.DEFAULT_POLICY)

    def test_hf_and_supreme_court_policy_rows(self):
        # huggingface.co mirrors the datasets-server values; supreme.court.gov.ua pause_s=1.5
        # matches the watcher's observed self-throttle.
        hf = P.policy("huggingface.co")
        self.assertEqual((hf["pause_s"], hf["req_per_day"], hf["bytes_per_day"]),
                         (1.0, 20_000, 8_000_000_000))
        sc = P.policy("supreme.court.gov.ua")
        self.assertEqual((sc["pause_s"], sc["req_per_min"], sc["bytes_per_day"]),
                         (1.5, 40, 2_000_000_000))
        # both rows carry an ENFORCED byte cap (not None) so acquire() DEFERs when hit.
        self.assertIsNotNone(hf["bytes_per_day"])
        self.assertIsNotNone(sc["bytes_per_day"])

    @_WINDOWS_LOCK
    def test_inter_request_pause_enforced(self):
        P.POLICIES["ZZ-P"] = {"pause_s": 0.2, "req_per_min": None, "req_per_day": 100,
                              "bytes_per_day": 10**9}
        t = time.time()
        P.acquire("ZZ-P")
        P.acquire("ZZ-P")
        self.assertGreaterEqual(time.time() - t, 0.2)

    @_WINDOWS_LOCK
    def test_daily_request_cap_defers(self):
        P.POLICIES["ZZ-C"] = {"pause_s": 0.0, "req_per_min": None, "req_per_day": 2,
                              "bytes_per_day": 10**9}
        P.acquire("ZZ-C")
        P.acquire("ZZ-C")
        with self.assertRaises(P.BudgetExceeded):
            P.acquire("ZZ-C")

    @_WINDOWS_LOCK
    def test_byte_cap(self):
        P.POLICIES["ZZ-B"] = {"pause_s": 0.0, "req_per_min": None, "req_per_day": None,
                              "bytes_per_day": 1000}
        self.assertTrue(P.can_spend("ZZ-B", 500))
        P.spend("ZZ-B", 900)
        self.assertEqual(P.used("ZZ-B")["bytes"], 900)
        self.assertFalse(P.can_spend("ZZ-B", 200))   # 900 + 200 > 1000

    @_WINDOWS_LOCK
    def test_daily_byte_cap_enforced_in_acquire(self):
        # the byte cap is ENFORCED (not accounting-only) — once today's bytes reach the
        # cap, acquire() raises BudgetExceeded so the collector DEFERs.
        P.POLICIES["ZZ-BC"] = {"pause_s": 0.0, "req_per_min": None, "req_per_day": None,
                               "bytes_per_day": 1000}
        P.acquire("ZZ-BC")          # under cap → fine
        P.spend("ZZ-BC", 1000)      # reach the daily byte cap
        with self.assertRaises(P.BudgetExceeded):
            P.acquire("ZZ-BC")

    def test_state_file_keyed_by_frozen_kyiv_day(self):
        # Daily state is keyed by the Europe/Kyiv day and FROZEN per process (the same
        # convention as rada/budget.py), not a naive re-read of date.today().
        self.assertEqual(P._today(), P._TODAY.isoformat())        # frozen: _today() == _TODAY
        self.assertTrue(P._state_path("od.reyestr.court.gov.ua").name.endswith(f"_{P._today()}.json"))
        self.assertTrue(P._KYIV is None or str(P._KYIV) == "Europe/Kyiv")

    def test_compute_today_uses_kyiv_tz_not_naive(self):
        # _compute_today() must use the Kyiv tz — a naive date.today() mutant differs in the
        # 22:00-24:00-UTC window. Freeze a UTC instant that is the NEXT calendar day in Kyiv
        # (UTC+3, summer). ALSO mock datetime.date so a `date.today()` mutant returns the UTC
        # day (11th) — otherwise, on a machine whose real local date == 2026-07-12, the mutant
        # would survive undetected.
        if P._KYIV is None:
            self.skipTest("no IANA tzdata → documented naive fallback, tz assertion N/A")

        class _FrozenNow(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                base = datetime.datetime(2026, 7, 11, 22, 30, tzinfo=datetime.timezone.utc)
                return base.astimezone(tz) if tz is not None else base.replace(tzinfo=None)

        class _FrozenDate(datetime.date):
            @classmethod
            def today(cls):
                return datetime.date(2026, 7, 11)   # a `date.today()` mutant would land here

        with mock.patch.object(P.datetime, "datetime", _FrozenNow), \
             mock.patch.object(P.datetime, "date", _FrozenDate):
            # Kyiv is already on the 12th while UTC is still on the 11th.
            self.assertEqual(P._compute_today(), datetime.date(2026, 7, 12))

    def test_today_returns_frozen_value_not_a_reread(self):
        # _today() must return the FROZEN _TODAY, not re-read the clock. Under a mocked
        # clock set to a far-off day, a re-reading mutant (_compute_today()/date.today()) would
        # drift; the frozen value must not.
        class _OtherNow(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                base = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
                return base.astimezone(tz) if tz is not None else base.replace(tzinfo=None)

        class _OtherDate(datetime.date):
            @classmethod
            def today(cls):
                return datetime.date(2000, 1, 1)

        with mock.patch.object(P.datetime, "datetime", _OtherNow), \
             mock.patch.object(P.datetime, "date", _OtherDate):
            self.assertEqual(P._today(), P._TODAY.isoformat())   # frozen — ignores the mocked clock
            self.assertNotEqual(P._today(), "2000-01-01")        # a re-read mutant would give this

    @_WINDOWS_LOCK
    def test_locked_retries_then_acquires_on_transient_oserror(self):
        # msvcrt.LK_LOCK raises OSError under contention (its 10x1s internal wait expired).
        # _locked must RETRY, not surface a bare EDEADLOCK. Two failures, then success.
        import msvcrt
        calls = {"lock": 0}

        def flaky(fileno, mode, nbytes):
            if mode == msvcrt.LK_LOCK:
                calls["lock"] += 1
                if calls["lock"] <= 2:
                    raise OSError("locked")
            return None  # LK_LOCK (3rd) / LK_UNLCK succeed without touching a real region

        with mock.patch.object(msvcrt, "locking", flaky):
            with P._locked("ZZ-lock"):
                pass
        self.assertEqual(calls["lock"], 3)   # retried twice, acquired on the third attempt

    @_WINDOWS_LOCK
    def test_locked_gives_up_with_clear_error(self):
        # A permanently stuck holder must yield a clear RuntimeError, never a bare OSError.
        import msvcrt

        def always_stuck(fileno, mode, nbytes):
            if mode == msvcrt.LK_LOCK:
                raise OSError("stuck")
            return None

        with mock.patch.object(msvcrt, "locking", always_stuck):
            with self.assertRaises(RuntimeError):
                with P._locked("ZZ-lock2"):
                    pass

    @_WINDOWS_LOCK
    def test_single_flight_blocks_a_second_process(self):
        # cross-process: hold the lock here, a subprocess trying to take it must fail fast.
        child = (
            "import sys; sys.path.insert(0, '.')\n"
            "from pipelines import politeness as P\n"
            "from pathlib import Path\n"
            f"P._DIR = Path(r'{self.tmp.as_posix()}')\n"
            "try:\n"
            "    with P.single_flight('zztest'): print('ACQUIRED')\n"
            "except RuntimeError: print('BLOCKED')\n"
        )
        with P.single_flight("zztest"):
            r = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True,
                               cwd=str(Path(__file__).resolve().parents[1]))
        self.assertIn("BLOCKED", (r.stdout or "") + (r.stderr or ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
