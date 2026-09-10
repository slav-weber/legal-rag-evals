"""Per-act datred/edcnt backstop for the Rada freshness signal.

The act-aware r.txt signal (probe.py) only sees the ~24 h window of Rada's
recent-changes feed: a probe missed for a day, or a second consecutive edit of the
same act, silently vanishes. This second contour closes that gap. When the gate
opens — the r.txt signal reported `changed`, OR N days (default 7) have passed since
the last backstop — it re-pulls each seed act's card and compares the card's edition
count (`edcnt`) and latest edition date (`datred`) against what we have in `editions`.
Any divergence flags that act 🟡 (a new/withdrawn edition we would otherwise miss).

Cards are light (~0.5 MB each); the fetch is metered through the same Rada daily byte
budget (budget.py). Errors degrade gracefully — a failed card fetch is recorded, never
crashes the daily probe, and never poisons the baseline signal.

Run standalone (force a check):  uv run python -m pipelines.freshness.rada_backstop --force
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines.checks._common import get_json  # noqa: E402
from pipelines.db import connect, run_migrations  # noqa: E402
from pipelines.rada import budget  # noqa: E402
from pipelines.rada.fetch_cards import SEED_ACTS, edition_date  # noqa: E402

SOURCE_ID = "rada-backstop"
N_DAYS = 7
CARD_URL = "https://data.rada.gov.ua/laws/card/{q}.json"
CARD_EST_BYTES = 500_000


def card_state(card: dict) -> tuple[int, str | None]:
    """(edcnt, latest datred 'YYYYMMDD') from a Rada card's eds[], counted EXACTLY as
    fetch_cards writes editions: via the SAME edition_date() validator (a real calendar
    date, not merely 8 digits — 20260230 is rejected) and DEDUPED (the editions table has
    UNIQUE(act_nreg, edition_date), so a card that repeats a datred stores it once).

    The old form counted len() of every 8-digit isdigit() datred — duplicates
    and impossible dates (e.g. 20260230) inflated edcnt_card above edcnt_db, producing a
    FALSE mismatch on a corpus that is actually in sync. Mirroring the writer removes it."""
    eds = card.get("eds", []) or []
    dates = {edition_date(e.get("datred")) for e in eds}
    dates.discard(None)  # edition_date() returns None for malformed / impossible dates
    if not dates:
        return 0, None
    return len(dates), max(dates).strftime("%Y%m%d")


def db_state(conn, nreg: str) -> tuple[int, str | None]:
    """(edition_count, max edition_date 'YYYYMMDD') for an act in `editions`."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), max(edition_date) FROM editions WHERE act_nreg=%s", (nreg,))
        cnt, mx = cur.fetchone()
    return cnt, (mx.strftime("%Y%m%d") if mx else None)


def compare(nreg: str, card: dict, db: tuple[int, str | None]) -> dict:
    ec, dc = card_state(card)
    edb, ddb = db
    return {"nreg": nreg, "edcnt_card": ec, "edcnt_db": edb,
            "datred_card": dc, "datred_db": ddb,
            "mismatch": (ec != edb) or (dc != ddb)}


def _last_run_at(conn) -> datetime | None:
    # Gate on the last COMPLETE run only (signal_value IS NOT NULL). An
    # all-errored or budget-truncated run writes signal_value=NULL — it must NOT reset
    # the 7-day timer, or a single bad day would silence the backstop for a week while
    # nothing was actually verified.
    with conn.cursor() as cur:
        cur.execute("SELECT max(checked_at) FROM source_checks "
                    "WHERE source_id=%s AND signal_value IS NOT NULL", (SOURCE_ID,))
        return cur.fetchone()[0]


def _last_signal(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT signal_value FROM source_checks WHERE source_id=%s "
                    "AND signal_value IS NOT NULL ORDER BY checked_at DESC LIMIT 1", (SOURCE_ID,))
        row = cur.fetchone()
    return row[0] if row else None


def should_run(conn, rada_changed: bool, now: datetime | None = None, n_days: int = N_DAYS) -> bool:
    """Gate: run on a reported r.txt change, or unconditionally every n_days."""
    if rada_changed:
        return True
    now = now or datetime.now(timezone.utc)
    last = _last_run_at(conn)
    return last is None or (now - last).days >= n_days


def run(conn, rada_changed: bool = False, fetch=get_json, now: datetime | None = None,
        n_days: int = N_DAYS) -> dict:
    """Execute the backstop if the gate is open. Returns a summary dict."""
    if not should_run(conn, rada_changed, now, n_days):
        return {"ran": False, "reason": "gate closed (<N days and rada unchanged)"}
    # The source_registry row is owned by the SINGLE writer (probe._upsert_sources via
    # freshness/sources.py 'rada-backstop'); the inline self-INSERT here was removed. This
    # watcher writes ONLY source_checks (below).
    results: list[dict] = []
    errors: list[str] = []
    for nreg in SEED_ACTS:
        if not budget.can_spend(CARD_EST_BYTES):
            errors.append(f"{nreg}: Rada budget exhausted (deferred)")
            continue
        try:
            card = fetch(CARD_URL.format(q=quote(nreg, safe="")))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{nreg}: {exc}")
            continue
        try:
            budget.add(len(str(card).encode("utf-8")))
        except Exception:  # noqa: BLE001
            pass
        results.append(compare(nreg, card, db_state(conn, nreg)))

    mism = [r for r in results if r["mismatch"]]
    # signal = hash of per-act (edcnt, datred). Only a COMPLETE run (every
    # seed act fetched+compared) yields a real signal. A partial run (budget-deferred or
    # fetch-errored acts) would hash a SUBSET → its hash differs from the full-set
    # baseline and flips `changed` to a FALSE 🟡; an all-errored run has nothing to hash.
    # Both write signal_value=NULL → `changed` stays False (no false 🟡) AND the 7-day
    # gate — which counts non-NULL runs only — is not reset, so the deferred acts are
    # retried at the next opportunity instead of being silenced for a week.
    complete = len(results) == len(SEED_ACTS)
    sig: str | None
    if results and complete:
        state = "|".join(f"{r['nreg']}:{r['edcnt_card']}:{r['datred_card']}" for r in results)
        sig = hashlib.sha256(state.encode("utf-8")).hexdigest()[:16]
    else:
        sig = None
    kind = "complete" if complete else ("all-error" if not results else "partial")
    note = (f"{len(results)}/{len(SEED_ACTS)} acts checked ({kind}); mismatches: "
            f"{', '.join(r['nreg'] for r in mism) if mism else 'none'}"
            + (f"; fetch-errors: {len(errors)}" if errors else ""))
    prev = _last_signal(conn)
    changed = bool(prev is not None and sig is not None and sig != prev)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO source_checks (source_id, signal_value, changed, note) "
                    "VALUES (%s,%s,%s,%s)", (SOURCE_ID, sig, changed, note))
    conn.commit()
    return {"ran": True, "results": results, "mismatches": mism, "errors": errors,
            "changed": changed, "signal": sig, "note": note, "complete": complete}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Rada seed-act datred/edcnt backstop (R-05)")
    ap.add_argument("--force", action="store_true", help="run regardless of the N-day gate")
    args = ap.parse_args()
    run_migrations()
    with connect() as conn:
        res = run(conn, rada_changed=args.force)
    if not res["ran"]:
        print(f"backstop: {res['reason']}")
        return 2
    print(f"backstop: {res['note']}")
    for r in res["mismatches"]:
        print(f"  ! {r['nreg']}: card(edcnt={r['edcnt_card']},datred={r['datred_card']}) "
              f"!= db(edcnt={r['edcnt_db']},datred={r['datred_db']})")
    if res["errors"]:
        for e in res["errors"]:
            print(f"  ~ {e}")
    # honest exit: mismatches or fetch-errors -> non-zero
    return 1 if (res["mismatches"] or res["errors"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
