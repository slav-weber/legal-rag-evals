"""The freshness probe compares every new signal with the source's last SUCCESSFUL one. A failed
probe (a Rada 403, a timeout) writes signal_value = NULL; were that NULL the previous signal, the
next real signal would be compared with it, `changed` would stay False and the move would pass
into the baseline unflagged: a new edition of a seed act that lands around a failed probe would
never turn the source yellow.

The real _last_signal query runs against an in-memory SQLite table with the columns it reads; the
adapter maps psycopg's %s placeholders to SQLite's ?.

    uv run python -m unittest discover -s tests -p test_freshness_last_signal.py -q
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.freshness import probe  # noqa: E402


class _Cursor:
    def __init__(self, cur: sqlite3.Cursor):
        self._cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._cur.close()
        return False

    def execute(self, sql, params=()):
        self._cur.execute(sql.replace("%s", "?"), params)

    def fetchone(self):
        return self._cur.fetchone()


class _Conn:
    """psycopg-shaped access (`with conn.cursor() as cur`, %s placeholders) to source_checks."""

    def __init__(self, rows):
        self._db = sqlite3.connect(":memory:")
        self._db.execute("CREATE TABLE source_checks "
                         "(source_id TEXT, signal_value TEXT, checked_at TEXT)")
        self._db.executemany("INSERT INTO source_checks VALUES (?, ?, ?)", rows)

    def cursor(self):
        return _Cursor(self._db.cursor())

    def close(self):
        self._db.close()


class LastSignal(unittest.TestCase):
    def _last(self, rows, source_id="rada"):
        conn = _Conn(rows)
        self.addCleanup(conn.close)
        return probe._last_signal(conn, source_id)

    def test_a_failed_probe_null_is_not_the_previous_signal(self):
        rows = [("rada", "A", "2026-09-01T06:00:00"),      # a real signal
                ("rada", None, "2026-09-02T06:00:00")]     # then a failed probe
        self.assertEqual(self._last(rows), "A")

    def test_the_latest_successful_signal_of_this_source_wins(self):
        rows = [("rada", "A", "2026-09-01T06:00:00"),
                ("rada", "B", "2026-09-02T06:00:00"),
                ("rada", None, "2026-09-03T06:00:00"),
                ("hf", "Z", "2026-09-04T06:00:00")]        # another source, newer still
        self.assertEqual(self._last(rows), "B")


if __name__ == "__main__":
    unittest.main(verbosity=2)
