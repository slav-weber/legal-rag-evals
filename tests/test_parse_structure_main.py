"""The parse run's exit code and COLLECT-SUMMARY line. An edition whose amendment quote never
closes has had its structural tail suppressed, so the run that parsed it is a failed run, never a
clean one: a run in which something failed never exits 0. The detector itself is pinned in
test_parse_structure_t9.py; these drive main() with the database, DATA_DIR and the edition list
faked in memory, and the edition TXT in a temporary directory.

    uv run python -m unittest discover -s tests -p test_parse_structure_main.py -q
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines import exitcodes, summary  # noqa: E402
from pipelines.rada import parse_structure as PS  # noqa: E402

_HEAD = ["ЗАКОН УКРАЇНИ", "Про щось", "",
         "Стаття 1. Сфера дії", "", "1. Цей Закон регулює відносини.", "",
         "Стаття 2. Прикінцеві положення", "", "1. Внести зміни до Кодексу:", "",
         "є) доповнити статтею 5 такого змісту:", "",
         '"Стаття 5. Назва процитованої статті', ""]
_TAIL = ["Стаття 3. Набрання чинності", "", "1. Цей Закон набирає чинності.", ""]
# the quote closes, so Стаття 3 is this act's own article again
CLOSED = "\n".join([*_HEAD, 'Текст процитованої статті";', "", *_TAIL])
# the quote never closes: Стаття 3 and everything after it is swallowed by the quoted block
UNCLOSED = "\n".join([*_HEAD, "Текст процитованої статті без закриваючої лапки.", "", *_TAIL])


class _Cursor:
    """Takes the unit writes; the per-kind count query finds nothing."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        pass

    def executemany(self, sql, rows):
        self._conn.units_written += len(list(rows))

    def fetchall(self):
        return []


class _Conn:
    def __init__(self):
        self.units_written = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        pass


class ParseRunExitCode(unittest.TestCase):
    def _run(self, editions: dict[str, str]) -> tuple[int, dict | None, _Conn]:
        """main() over one act whose editions are {YYYYMMDD: TXT}. Returns the exit code, the
        parsed COLLECT-SUMMARY line and the fake connection."""
        data = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, data, ignore_errors=True)
        rows = []
        for ymd, text in editions.items():
            rel = f"raw/rada/txt/TEST-1/ed{ymd}.txt"
            (data / rel).parent.mkdir(parents=True, exist_ok=True)
            (data / rel).write_text(text, encoding="utf-8")
            rows.append((date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:])), rel))
        conn, out = _Conn(), io.StringIO()
        with mock.patch.object(sys, "argv", ["parse_structure", "TEST-1"]), \
             mock.patch("pipelines.orchestration.warn_if_standalone"), \
             mock.patch.object(PS, "connect", return_value=conn), \
             mock.patch.object(PS, "DATA_DIR", data), \
             mock.patch.object(PS, "_editions", return_value=rows), \
             redirect_stdout(out):
            code = PS.main()
        return code, summary.parse(out.getvalue()), conn

    def test_an_unclosed_amendment_quote_fails_the_run(self):
        code, s, _conn = self._run({"20260101": CLOSED, "20250101": UNCLOSED})
        self.assertEqual(code, exitcodes.FAIL)
        self.assertIsNotNone(s)
        self.assertGreater(s["failed"], 0)          # the orchestrator journals a failure

    def test_clean_editions_exit_ok(self):
        code, s, conn = self._run({"20260101": CLOSED, "20250101": CLOSED})
        self.assertEqual(code, exitcodes.OK)
        self.assertEqual((s["ok"], s["failed"]), (2, 0))
        self.assertGreater(conn.units_written, 0)   # both editions really went through _write


if __name__ == "__main__":
    unittest.main(verbosity=2)
