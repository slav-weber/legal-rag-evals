"""Fetch edition TXT for the seed acts into DATA_DIR/raw/rada/txt.

For every seed act (priority order below), fetch the TXT of each edition recorded
in the editions table, save it under raw/rada/txt/{nreg}/ed{YYYYMMDD}.txt and record
a DATA_DIR-relative POSIX path in editions.txt_path. Idempotent: editions already on
disk are skipped, so re-running only fills gaps.

Budget: downloads are metered against the per-day Rada traffic budget
(pipelines/rada/budget.py, ≤180 MB/day). When the day's budget is exhausted the
remaining editions are DEFERRED (reported, not fetched) and picked up on a later
run/day — priority order is respected (КАС first, КУпАП last).

Hardening: only HTTP 404 = "no text served"; 429/5xx are retried with
backoff and, if still failing, make the run exit non-zero; a U+FFFD in the decoded
text is refused, not written.

Run:  uv run python -m pipelines.rada.fetch_texts
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines import summary as _summary  # noqa: E402
from pipelines.checks._common import get, header  # noqa: E402
from pipelines.db import connect  # noqa: E402
from pipelines.paths import RAW_DIR, rel  # noqa: E402
from pipelines.rada import budget  # noqa: E402

# Priority order: КАС (the main worked example) first; the three earliest-collected acts
# skip fast; КУпАП (80731/80732) are the heaviest → last, spread across the daily budget.
PRIORITY_ACTS = [
    "2747-15", "2232-12", "3674-17", "76-2023-п", "3633-IX",
    "3543-12", "560-2024-п", "z1109-08", "80731-10", "80732-10",
    "1404-19",  # last: the КУпАП tail keeps daily-budget priority
    "8073-10",  # modern КУпАП, last: 121 eds × ~1.74 MB ≈ 210 MB > daily cap →
                # fetch wartime first via `--since 2022-01-01`, older history self-defers.
    # 76-2024-п → 76-2023-п (see fetch_cards.SEED_ACTS). 76-2024-п text stays on
    # disk as provenance; not re-listed here (excluded from the seed manifest).
]
SHOW_TXT = "https://data.rada.gov.ua/laws/show/{q}/ed{ymd}.txt"
TXT_DIR = RAW_DIR / "rada" / "txt"
RETRIES = 4
DEFER_RESERVE = 2 * 1024 * 1024  # stop fetching when < 2 MB budget remains today


def edition_selector(since: str | None, current: bool) -> tuple[str, str, str, list]:
    """Build (where, order, limit, extra_params) for the per-act edition query.

    --since D : in-force editions on/after D, NEWEST first (cover the recent/wartime
                tail before the byte budget defers older history); extra param [D]
    --current : the single latest in-force edition
    default   : full history, oldest first
    """
    if since:
        return ("AND edition_date >= %s AND edition_date <= CURRENT_DATE", "DESC", "", [since])
    if current:
        return ("AND edition_date <= CURRENT_DATE", "DESC", " LIMIT 1", [])
    return ("", "ASC", "", [])


class TransientError(RuntimeError):
    """A 429/5xx that persisted through all retries — the run should fail."""


def fetch_txt(nreg: str, ymd: str) -> tuple[str | None, int]:
    """Return (text|None, downloaded_bytes). None text = no text served (404/empty).
    Retries 429/5xx with backoff; raises TransientError if it never succeeds."""
    url = SHOW_TXT.format(q=quote(nreg, safe=""), ymd=ymd)
    status = None
    for attempt in range(RETRIES):
        r = get(url)
        status = r.status_code
        if status == 200:
            r.encoding = "utf-8"
            text = r.text
            return (text if text.strip() else None), len(r.content)
        if status == 404:
            return None, len(r.content)
        wait = 8 * (attempt + 1)
        print(f"  ed{ymd}: HTTP {status} -> retry in {wait}s ({attempt + 1}/{RETRIES})")
        time.sleep(wait)
    raise TransientError(f"{nreg} ed{ymd}: persistent HTTP {status} after {RETRIES} tries")


def main() -> int:
    from pipelines.orchestration import warn_if_standalone
    warn_if_standalone("A-03 (rada.fetch_texts)")  # loud unless orchestrated
    import argparse
    ap = argparse.ArgumentParser(description="Fetch Rada edition TXT (A-03 / targeted)")
    ap.add_argument("--acts", nargs="+", help="specific nreg(s) — targeted, NOT the seed")
    ap.add_argument("--current", action="store_true", help="only the latest edition per act")
    ap.add_argument("--since", metavar="YYYY-MM-DD",
                    help="only in-force editions on/after this date, NEWEST first "
                         "(R-19v2: cover recent/wartime editions before the byte budget "
                         "defers older history)")
    args = ap.parse_args()
    acts = args.acts or PRIORITY_ACTS

    header("fetch_texts — edition TXT (A-03; budgeted)" + (" [targeted]" if args.acts else ""))
    print(f"Rada budget today: used={budget.used() / 1e6:.1f} MB, "
          f"remaining={budget.remaining() / 1e6:.1f} MB (cap {budget.CAP_BYTES / 1e6:.0f} MB)")
    saved = skipped = no_text = deferred = 0
    bytes_dl = 0
    errors: list[str] = []
    budget_stopped = False

    with connect() as conn:
        for nreg in acts:
            # Edition selection:
            #   --since D : in-force editions on/after D, NEWEST first (cover the recent/
            #               wartime tail before the byte budget defers older history)
            #   --current : the single latest in-force edition
            #   default   : full history, oldest first
            # --current/--since fetch the in-force edition, not a future/placeholder one
            # (year 3000/2027…). Full-history mode still fetches every edition Rada offers,
            # including scheduled ones.
            where, order, limit, extra = edition_selector(args.since, args.current)
            params: list = [nreg, *extra]
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT edition_date, size FROM editions WHERE act_nreg = %s "
                    f"{where} ORDER BY edition_date {order}{limit}",
                    params,
                )
                rows = cur.fetchall()
            out_dir = TXT_DIR / nreg
            out_dir.mkdir(parents=True, exist_ok=True)
            act_saved = act_skipped = act_deferred = 0

            for ed, size in rows:
                ymd = ed.strftime("%Y%m%d")
                path = out_dir / f"ed{ymd}.txt"
                if path.exists() and path.stat().st_size > 0:
                    skipped += 1
                    act_skipped += 1
                    _set_path(conn, nreg, ed, rel(path))
                    continue
                est = int(size) if size else 500_000
                if budget_stopped or budget.remaining() < DEFER_RESERVE or not budget.can_spend(est):
                    budget_stopped = True
                    deferred += 1
                    act_deferred += 1
                    continue
                try:
                    text, nbytes = fetch_txt(nreg, ymd)
                except TransientError as exc:
                    errors.append(str(exc))
                    print(f"  ! {exc}")
                    continue
                budget.add(nbytes)
                bytes_dl += nbytes
                if text is None:
                    no_text += 1
                    print(f"  {nreg} ed{ymd}: no text served (404/empty)")
                    continue
                if "�" in text:
                    errors.append(f"{nreg} ed{ymd}: U+FFFD in decoded text — not written")
                    print(f"  ! {nreg} ed{ymd}: U+FFFD (mojibake) — skipped")
                    continue
                # atomic write: a kill / disk-full mid-write must never leave a
                # truncated TXT that the size>0 skip would then accept forever. Write
                # to a temp file and os.replace() it into place — the final path only
                # ever exists complete. NB: editions.size is
                # Rada's declared source-doc size (cp1251/raw), NOT the UTF-8 text byte
                # count (~0.6–0.7× and variable), so it is unusable as a length check —
                # the atomic rename is the completeness guarantee here.
                tmp = path.with_name(path.name + ".part")
                tmp.write_text(text, encoding="utf-8")
                os.replace(tmp, path)
                _set_path(conn, nreg, ed, rel(path))
                saved += 1
                act_saved += 1

            print(f"  {nreg:14s} saved={act_saved:4d} skipped={act_skipped:4d} deferred={act_deferred:4d} "
                  f"(of {len(rows)})")

    print(f"\nDONE: saved={saved}, skipped(existing)={skipped}, no-text(404)={no_text}, "
          f"deferred(budget)={deferred}, errors={len(errors)}")
    print(f"downloaded this run: {bytes_dl / 1e6:.1f} MB; Rada budget remaining: "
          f"{budget.remaining() / 1e6:.1f} MB")
    if deferred:
        print(f"NOTE: {deferred} editions deferred to a later day (Rada daily budget). Re-run to resume.")
    for e in errors:
        print(f"  ! {e}")
    _summary.emit(ok=saved, failed=len(errors), nbytes=int(bytes_dl))  # honest counts
    return 1 if errors else 0


def _set_path(conn, nreg: str, ed, rel_path: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE editions SET txt_path = %s WHERE act_nreg = %s AND edition_date = %s",
            (rel_path, nreg, ed),
        )
    conn.commit()


if __name__ == "__main__":
    raise SystemExit(main())
