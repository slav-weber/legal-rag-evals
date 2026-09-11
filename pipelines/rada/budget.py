"""Per-day traffic budget for data.rada.gov.ua.

Rada's open-data daily limit is 200 MB; we cap at 180 MB/day (decimal MB, matching
how every caller prints ``/1e6``) and resume the next day. The counter is persisted
per calendar day at data/raw/rada/.traffic/<date>.json so multiple runs on the same
day accumulate. On first use of a given day the counter is seeded from the total size
of files under the Rada-budget subtrees (raw/rada + raw/ksu — КСУ, the Constitutional
Court, is served from data.rada.gov.ua too) modified that day, so downloads already made
today by fetch_cards / fetch_texts / ksu.snapshot are accounted for.

The day is Europe/Kyiv and FROZEN per process (computed once at import), so a run that
crosses local midnight can't split its accounting across two files.
"""

from __future__ import annotations

import datetime
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines.paths import RAW_DIR  # noqa: E402

RADA_DIR = RAW_DIR / "rada"
KSU_DIR = RAW_DIR / "ksu"
_TRAFFIC_DIR = RADA_DIR / ".traffic"
_BUDGET_DIRS = (RADA_DIR, KSU_DIR)          # subtrees that spend the Rada budget
CAP_BYTES = 180_000_000                     # decimal 180 MB (one convention everywhere)

try:
    _KYIV = ZoneInfo("Europe/Kyiv")
except Exception:  # noqa: BLE001 — missing IANA db (tzdata): degrade to local time
    _KYIV = None
_TODAY = datetime.datetime.now(_KYIV).date()  # Kyiv day, frozen per process


def _today() -> str:
    return _TODAY.isoformat()


def _file() -> Path:
    return _TRAFFIC_DIR / f"{_today()}.json"


def _seed_today() -> int:
    """Bytes of files under the Rada-budget subtrees modified today (excl. .traffic)."""
    total = 0
    for base in _BUDGET_DIRS:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and _TRAFFIC_DIR not in p.parents:
                try:
                    if datetime.datetime.fromtimestamp(
                            p.stat().st_mtime, _KYIV).date() == _TODAY:
                        total += p.stat().st_size
                except OSError:
                    pass
    return total


def used() -> int:
    f = _file()
    if f.exists():
        return int(json.loads(f.read_text())["bytes"])
    seed = _seed_today()
    _write(seed)
    return seed


def _write(total: int) -> None:
    _TRAFFIC_DIR.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps({"date": _today(), "bytes": int(total)}))


def remaining() -> int:
    return max(0, CAP_BYTES - used())


def can_spend(nbytes_estimate: int = 0) -> bool:
    return used() + nbytes_estimate <= CAP_BYTES


@contextmanager
def _locked():
    """Cross-process exclusive lock so the add() read-modify-write can't lose an update when two
    collectors spend the Rada budget concurrently.

    The same primitives and bounded-wait contract as politeness._locked: msvcrt on Windows,
    fcntl.flock elsewhere. A bounded attempt raises OSError after about 10 s — it does NOT block
    forever. Our critical section is microseconds, so 10 s of contention means a stuck holder;
    retry a bounded number of times and surface a clear error rather than letting a bare
    EDEADLOCK escape from inside add()."""
    from pipelines.politeness import _lock_bounded, _unlock
    _TRAFFIC_DIR.mkdir(parents=True, exist_ok=True)
    f = open(_TRAFFIC_DIR / "budget.lock", "a+")
    try:
        for attempt in range(6):  # up to ~60 s (6 × the bounded 10 s) before giving up
            try:
                _lock_bounded(f)
                break
            except OSError:
                if attempt == 5:
                    raise RuntimeError("rada budget: could not lock budget.lock after ~60s "
                                       "(a holder is stuck) — refusing to risk a lost update")
        try:
            yield
        finally:
            try:
                _unlock(f)
            except OSError:
                pass
    finally:
        f.close()


def add(nbytes: int) -> None:
    # Concurrency-safe read-modify-write — two runs adding at once must not lose an update.
    with _locked():
        _write(used() + int(nbytes))
