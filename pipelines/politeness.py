"""Per-host politeness/budget layer + a cross-process single-flight lock (Windows and POSIX).

The contract is that the ORCHESTRATOR — not each script's own discipline — meters per-host
request rate and daily volume and self-stops. This provides that, keyed by a per-host POLICY
TABLE (NOT one-size Rada constants, which would cripple the court-text backfill: 5–7 s × 135k
od.reyestr texts ≈ 9 days). Rada keeps its strict numbers; od.reyestr — a bulk court registry
with no stated rate limit — gets a policy that keeps the fetch workers effective.

State is file-based under DATA_DIR/.traffic/ and guarded by a cross-process file lock: the
Windows-native **msvcrt** lock on the production Windows box (verified working) and
**fcntl.flock** everywhere else (Linux CI, containers), both behind one bounded-wait contract.
Composing across the orchestrator's subprocesses AND the court-registry worker threads is exactly
why the state lives on disk under a cross-process lock rather than in a process-local timestamp.

The od.reyestr / data.gov.ua / HF / default values below are deliberate settings, not defaults
(od.reyestr pause_s was later tightened 0.0→0.2; the Rada row is reference-only). They were
chosen conservatively from each host's PUBLISHED terms (od.reyestr docs: "no captcha / no daily
limit, be courteous"; Rada's ≤200 MB/day) and courteous defaults — NOT from a measured 429/ban
history, which we have not collected.
"""

from __future__ import annotations

import datetime
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.paths import DATA_DIR  # noqa: E402

# Daily state files are keyed by the Europe/Kyiv day, FROZEN per process — same
# convention as rada/budget.py — so a run that straddles local midnight keeps one budget day.
try:
    _KYIV = ZoneInfo("Europe/Kyiv")
except Exception:  # noqa: BLE001 — missing IANA db (tzdata): degrade to local time
    _KYIV = None


def _compute_today() -> datetime.date:
    """The current Europe/Kyiv calendar day. Kept as a function (not an inline expr) so a
    test can freeze the clock and prove it uses the Kyiv tz, not a naive local date.today()
    (which drifts one day off during the 22:00/23:00-UTC window)."""
    return datetime.datetime.now(_KYIV).date()


_TODAY = _compute_today()  # frozen per process at import


def _today() -> str:
    return _TODAY.isoformat()

# pause_s   : minimum inter-request pause for the host (the primary throttle).
# req_per_min : rolling-60s request ceiling (None = only the pause governs rate).
# req_per_day : daily request cap → DEFER when hit.
# bytes_per_day : daily byte cap → DEFER when hit.
POLICIES: dict[str, dict] = {
    # Rada — 180 MB/day is budget.py's SELF-CAP under Rada's ≤200 MB limit; ≤60/min,
    # ≤100k/day. REFERENCE-ONLY here (0 call-sites) until the Rada collectors route
    # _common.get through acquire(); today Rada politeness is _common.polite_sleep +
    # budget.py bytes.
    "data.rada.gov.ua": {"pause_s": 6.0, "req_per_min": 60, "req_per_day": 100_000,
                         "bytes_per_day": 180_000_000},
    # od.reyestr — bulk court text registry; docs: "no captcha / no daily limit, be courteous".
    # pause_s=0.2 smooths the req/min burst to ~5 rps global instead of 300 instant;
    # 137k × 0.2 s ≈ 7.6 h, so the backfill is not crippled, and 403-ban risk drops.
    # req/min=300, req/day=300k, bytes/day=3 GB: large scopes self-defer over days, like Rada.
    "od.reyestr.court.gov.ua": {"pause_s": 0.2, "req_per_min": 300, "req_per_day": 300_000,
                                "bytes_per_day": 3_000_000_000},
    # data.gov.ua CKAN — few requests, huge yearly ZIPs: light pause, wide cap.
    "data.gov.ua": {"pause_s": 1.0, "req_per_min": 60, "req_per_day": 5_000,
                    "bytes_per_day": 12_000_000_000},
    # HuggingFace datasets-server — API + parquet: light pause, moderate caps.
    # REFERENCE-ONLY (0 call-sites): fetch_slice hits huggingface.co, not this datasets-server host.
    "datasets-server.huggingface.co": {"pause_s": 1.0, "req_per_min": 120, "req_per_day": 20_000,
                                       "bytes_per_day": 8_000_000_000},
    # huggingface.co — hf.fetch_slice: dataset tree API + DuckDB parquet range reads.
    # Same values as the datasets-server row (that one stays reference-only).
    "huggingface.co": {"pause_s": 1.0, "req_per_min": 120, "req_per_day": 20_000,
                       "bytes_per_day": 8_000_000_000},
    # supreme.court.gov.ua — the Supreme Court watcher: listing + case-law review PDFs.
    # pause_s=1.5 matches the watcher's observed self-throttle (DEFAULT 6 s would be ×4 slower).
    "supreme.court.gov.ua": {"pause_s": 1.5, "req_per_min": 40, "req_per_day": 2_000,
                             "bytes_per_day": 2_000_000_000},
}
# Unknown host → CONSERVATIVE (a slow, small default until a policy is added deliberately).
DEFAULT_POLICY = {"pause_s": 6.0, "req_per_min": 30, "req_per_day": 10_000, "bytes_per_day": 100_000_000}

_DIR = DATA_DIR / ".traffic"


class BudgetExceeded(RuntimeError):
    """A per-host daily cap (requests or bytes) is exhausted — the caller should DEFER."""


def policy(host: str) -> dict:
    return POLICIES.get(host, DEFAULT_POLICY)


def _state_path(host: str) -> Path:
    return _DIR / f"{host.replace('/', '_')}_{_today()}.json"


# ── cross-process lock primitives ─────────────────────────────────────────────────────────────
# One contract on both platforms: _lock_bounded() waits about 10 s and then raises OSError if the
# lock is still held; _lock_now() raises OSError at once; _unlock() releases. Windows uses msvcrt,
# whose LK_LOCK retries 10×1 s internally; POSIX polls flock for the same 10 s, because a plain
# blocking flock() would wait forever. Each call opens its own handle, so the lock also separates
# threads of one process (msvcrt regions and flock locks are both per handle).
_POSIX_WAIT_S = 10.0

if sys.platform == "win32":
    def _lock_bounded(f) -> None:
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def _lock_now(f) -> None:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(f) -> None:
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    def _lock_bounded(f) -> None:
        deadline = time.monotonic() + _POSIX_WAIT_S
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def _lock_now(f) -> None:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(f) -> None:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


@contextmanager
def _locked(host: str):
    """Exclusive cross-process lock for one host's state file.

    A bounded attempt waits about 10 s and then RAISES OSError if the region is still held (see
    the primitives above) — it does NOT wait forever. Our critical sections are microseconds
    (load/mutate/save one small JSON), so 10 s of contention means the lock is stuck, not merely
    busy; we retry a bounded number of times and then surface a clear error rather than letting
    a bare EDEADLOCK escape from deep inside acquire()/spend()."""
    _DIR.mkdir(parents=True, exist_ok=True)
    f = open(_DIR / f"{host.replace('/', '_')}.lock", "a+")
    try:
        for attempt in range(6):  # up to ~60 s total (6 × the bounded 10 s) before giving up
            try:
                _lock_bounded(f)
                break
            except OSError:
                if attempt == 5:
                    raise RuntimeError(f"politeness: could not lock {host} state after ~60s "
                                       f"(a holder is stuck) — refusing to race the budget")
        try:
            yield
        finally:
            try:
                _unlock(f)
            except OSError:
                pass
    finally:
        f.close()


def _load(host: str) -> dict:
    p = _state_path(host)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"reqs": 0, "bytes": 0, "last": 0.0, "win_start": 0.0, "win_reqs": 0}


def _save(host: str, st: dict) -> None:
    _state_path(host).write_text(json.dumps(st))


def acquire(host: str) -> None:
    """Block until it is polite to issue ONE request to `host`: honor the per-host
    inter-request pause and the rolling per-minute ceiling. Raise BudgetExceeded if the daily
    request cap is already hit (caller DEFERs). Cross-process/thread safe via the file lock.

    (The sleep is performed OUTSIDE the lock so one waiting collector cannot block others'
    accounting; the timestamp/counter updates are inside the lock.)"""
    pol = policy(host)
    while True:
        with _locked(host):
            st = _load(host)
            # BOTH daily caps are enforced here (they were accounting-only) — the policy
            # table must actually govern behaviour, so acquire() DEFERs when a cap is hit.
            if pol["req_per_day"] is not None and st["reqs"] >= pol["req_per_day"]:
                raise BudgetExceeded(f"{host}: daily request cap {pol['req_per_day']} reached")
            if pol["bytes_per_day"] is not None and st["bytes"] >= pol["bytes_per_day"]:
                raise BudgetExceeded(f"{host}: daily byte cap {pol['bytes_per_day']} reached")
            now = time.time()
            wait = 0.0
            # inter-request pause
            gap = now - st["last"]
            if pol["pause_s"] and gap < pol["pause_s"]:
                wait = max(wait, pol["pause_s"] - gap)
            # rolling 60s window
            if pol["req_per_min"] is not None:
                if now - st["win_start"] >= 60.0:
                    st["win_start"], st["win_reqs"] = now, 0
                if st["win_reqs"] >= pol["req_per_min"]:
                    wait = max(wait, 60.0 - (now - st["win_start"]))
            if wait <= 0:
                st["last"] = now
                st["reqs"] += 1
                st["win_reqs"] += 1
                _save(host, st)
                return
        time.sleep(min(wait, 60.0))  # release the lock, then wait, then re-check


def can_spend(host: str, nbytes: int) -> bool:
    pol = policy(host)
    if pol["bytes_per_day"] is None:
        return True
    with _locked(host):
        return _load(host)["bytes"] + nbytes <= pol["bytes_per_day"]


def spend(host: str, nbytes: int) -> None:
    """Record `nbytes` downloaded from `host` toward its daily byte cap."""
    with _locked(host):
        st = _load(host)
        st["bytes"] += int(nbytes)
        _save(host, st)


def used(host: str) -> dict:
    """(reqs, bytes) spent today for `host` — for the orchestrator journal / plan."""
    with _locked(host):
        st = _load(host)
        return {"reqs": st["reqs"], "bytes": st["bytes"]}


@contextmanager
def single_flight(name: str = "orchestrator"):
    """Non-blocking cross-process lock: the orchestrator takes it around a --run batch so
    a second `collect --all` (cron overlap / manual+cron) fails fast instead of double-running
    and racing the byte budget. Raises RuntimeError if another run already holds it."""
    _DIR.mkdir(parents=True, exist_ok=True)
    f = open(_DIR / f"{name}.singleflight.lock", "a+")
    try:
        try:
            _lock_now(f)
        except OSError as exc:
            raise RuntimeError(f"another '{name}' run holds the single-flight lock") from exc
        try:
            yield
        finally:
            try:
                _unlock(f)
            except OSError:
                pass
    finally:
        f.close()
