"""Snapshot the КСУ (Constitutional Court) decisions referenced by the 11 seed acts.

These 27 nregs were extracted deterministically from the seed acts' card_json /
editions.pidstava (nreg pattern ``v\\d+p710-\\d+``) and verified live as typ=22
(рішення КСУ). Decision of 2026-07-06: snapshot all 26 new ones (v002p710-26 =
2-р/2026 was already on disk).

Each decision text is pulled from Rada open data (``/laws/show/{nreg}.txt``, UA
OpenData, ≥6 s pauses) and stored under ``$DATA_DIR/raw/ksu/{N}-r-{YYYY}_{nreg}.txt``
with sha256 + a ``snapshots`` row (artifact_id C-03, kind ksu-txt), matching the
2-р/2026 precedent. A U+FFFD in the decoded text is refused, not written.

Budget: metered against the per-day Rada traffic budget (≤180 MB/day). When the
day's budget can't fit the next fetch the run stops cleanly (honest STOP) and is
resumed by re-running on a later day — already-snapshotted nregs skip (idempotent).

Run:  uv run python -m pipelines.ksu.snapshot
"""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines import exitcodes  # noqa: E402
from pipelines.checks._common import get, header  # noqa: E402
from pipelines.db import connect  # noqa: E402
from pipelines.paths import RAW_DIR, rel  # noqa: E402
from pipelines.rada import budget  # noqa: E402

# 27 КСУ decisions confirmed live as typ=22, referenced by the 11 seed acts.
# Decision of 2026-07-06: snapshot all of them. v002p710-26 is already on disk
# from the verification pass — it skips idempotently.
NREGS = [
    "v002p710-15", "v002p710-19", "v002p710-23", "v002p710-25", "v002p710-26",
    "v003p710-12", "v003p710-15", "v003p710-23", "v004p710-09", "v004p710-23",
    "v005p710-11", "v005p710-15", "v006p710-24", "v008p710-08", "v010p710-08",
    "v010p710-10", "v010p710-11", "v012p710-13", "v013p710-00", "v016p710-11",
    "v016p710-12", "v017p710-11", "v019p710-10", "v019p710-11", "v021p710-10",
    "v023p710-10", "v026p710-09",
]

KSU_DIR = RAW_DIR / "ksu"
_NREG_RE = re.compile(r"^v(\d+)p710-(\d+)$")
DEFER_RESERVE = 2 * 1024 * 1024  # stop when < 2 MB budget remains today


def label(nreg: str) -> str:
    """v002p710-26 -> '2-r-2026'.  p710 = рішення КСУ; number+year are exact."""
    m = _NREG_RE.match(nreg)
    if not m:
        return nreg
    n, yy = int(m.group(1)), int(m.group(2))
    year = (1900 if yy >= 90 else 2000) + yy  # КСУ since 1997; 20xx for 00–30
    return f"{n}-r-{year}"


def exit_code(errors: list[str], bad_char: list[str], deferred: int = 0, saved: int = 0) -> int:
    """Honest exit, per the shared exit-code convention. errors (HTTP/network) or U+FFFD-refusals
    -> FAIL(1); a pure planned budget defer with nothing else accomplished -> SKIP(2)
    with a NOTE (legitimate resume point); otherwise OK(0)."""
    if errors or bad_char:
        return exitcodes.FAIL
    if deferred and not saved:
        return exitcodes.SKIP
    return exitcodes.OK


def already_done(conn, nreg: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM snapshots WHERE artifact_id='C-03' AND url LIKE %s LIMIT 1",
            (f"%/{nreg}.txt",))
        return cur.fetchone() is not None


def main() -> int:
    from pipelines.orchestration import warn_if_standalone
    warn_if_standalone("C-03 (ksu.snapshot)")  # loud unless orchestrated
    header("C-03 — КСУ decision snapshots (budgeted)")
    print(f"Rada budget today: used={budget.used() / 1e6:.1f} MB, "
          f"remaining={budget.remaining() / 1e6:.1f} MB (cap {budget.CAP_BYTES / 1e6:.0f} MB)")
    KSU_DIR.mkdir(parents=True, exist_ok=True)

    saved = skipped = deferred = 0
    errors: list[str] = []
    bad_char: list[str] = []
    with connect() as conn:
        for nreg in NREGS:
            if already_done(conn, nreg):
                skipped += 1
                continue
            # Rada daily-budget gate (decision texts run ~30–80 KB; reserve 2 MB).
            est = 100 * 1024
            if budget.remaining() < DEFER_RESERVE or not budget.can_spend(est):
                deferred += 1
                continue

            url = f"https://data.rada.gov.ua/laws/show/{nreg}.txt"
            try:
                r = get(url, ua="OpenData")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{nreg}: {exc}")
                print(f"  ! {nreg}: {exc}")
                continue
            budget.add(len(r.content))
            if r.status_code != 200:
                errors.append(f"{nreg}: HTTP {r.status_code}")
                print(f"  ! {nreg}: HTTP {r.status_code}")
                continue

            r.encoding = "utf-8"
            text = r.text
            if not text.strip() or "�" in text:
                bad_char.append(nreg)
                print(f"  ! {nreg}: empty or U+FFFD in decoded text — refused")
                continue

            data = text.encode("utf-8")
            sha = hashlib.sha256(data).hexdigest()
            path = KSU_DIR / f"{label(nreg)}_{nreg}.txt"
            # write_bytes, NOT write_text: on Windows write_text(newline=None) translates
            # LF->CRLF, so the file on disk would differ from the hashed `data` (LF) and
            # snapshots.sha256 would be a dead column.
            path.write_bytes(data)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO snapshots
                       (artifact_id, url, sha256, bytes, kind, http_status, raw_path, fetched_at)
                       VALUES ('C-03', %s, %s, %s, 'ksu-txt', 200, %s, %s)""",
                    (url, sha, len(data), rel(path),
                     datetime.now(timezone.utc)))
            conn.commit()
            saved += 1
            print(f"  + {nreg} -> {path.name}  ({len(data):,} B, sha {sha[:12]}…)")

    print(f"\nDONE: saved={saved}, skipped(existing)={skipped}, "
          f"deferred(budget)={deferred}, errors={len(errors)}, U+FFFD-refused={len(bad_char)}")
    print(f"Rada budget remaining: {budget.remaining() / 1e6:.1f} MB")
    if deferred:
        print(f"NOTE: {deferred} decisions deferred to a later day (Rada daily budget). Re-run to resume.")
    if bad_char:
        print(f"U+FFFD refused (investigate encoding): {bad_char}")
    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  {e}")
    from pipelines import summary as _summary  # honest counts for the orchestrator
    _summary.emit(ok=saved, failed=len(errors) + len(bad_char), nbytes=0)  # Rada byte-metered → 0
    return exit_code(errors, bad_char, deferred, saved)


if __name__ == "__main__":
    raise SystemExit(main())
