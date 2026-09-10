"""T3 — fetch Rada act cards for the seed acts into Postgres (idempotent).

For each seed act: GET /laws/card/{nreg}.json (polite, UA OpenData), save the raw
JSON under data/raw/rada/, upsert the act, and upsert every edition parsed from
eds[]. Re-running does not duplicate rows (ON CONFLICT on the natural keys).

Run:  uv run python -m pipelines.rada.fetch_cards
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from urllib.parse import quote

from psycopg.types.json import Json

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines import exitcodes, summary as _summary  # noqa: E402
from pipelines.checks._common import get_json, header  # noqa: E402
from pipelines.db import connect, run_migrations  # noqa: E402
from pipelines.paths import RAW_DIR as _DATA_RAW  # noqa: E402
from pipelines.rada import budget  # noqa: E402

CARD_EST_BYTES = 500_000  # cards run small; a generous per-card budget reserve

# Seed acts — the corpus scope. Cyrillic 'п' / 'IX' in an nreg is kept verbatim;
# the URL path is percent-encoded per request.
SEED_ACTS = [
    "3543-12", "2232-12", "80731-10", "80732-10", "8073-10", "2747-15",
    "3674-17", "560-2024-п", "76-2023-п", "z1109-08", "3633-IX",
    "1404-19",  # 1404-VIII «Про виконавче провадження» (topic 1, edcnt≈74; added 2026-07-05)
    # Decision of 2026-07-09: 8073-10 is the MODERN КУпАП (Code of Administrative Offences) —
    # a consolidated, living document (is_archive=0, datred=20251211, edcnt=121,
    # n_vlas=8073-X). Since 07.05.2017 the Rada has frozen the two volumes 80731/80732-10 as
    # an archive («редакції до 07.05.2017») and maintains the code as a SINGLE document. It is
    # THE SAME act, inside the same scope. Volumes 80731/80732-10 are KEPT in the seed as the
    # historical layer (units up to 07.05.2017 are already parsed). The in-force КУпАП for
    # downstream chunking = the latest units of 8073-10. The key that maps a volume back to
    # its base act is card.n_vlas.
    # Decision of 2026-07-09: the seed is 76-2023-п «Деякі питання реалізації
    # положень Закону … щодо бронювання військовозобов'язаних» (Cabinet of Ministers
    # resolution No. 76 of 27.01.2023, is_archive=None, edcnt=38). The former seed 76-2024-п
    # was a single-edition AMENDING resolution, not a substantive one → dropped from the
    # manifest; its data (1 ed / 1 unit / 1 text) STAYS in the DB as provenance, outside
    # seed_alias_map (which is built from SEED_ACTS) — but the units ledger mirrors the DB
    # and therefore CARRIES the entry 76-2024-п|2024-01-23:1.
]
CARD_URL = "https://data.rada.gov.ua/laws/card/{q}.json"
RAW_DIR = _DATA_RAW / "rada"


def edition_date(datred) -> dt.date | None:
    """Parse an eds[].datred (YYYYMMDD int/str) into a date; None if malformed."""
    s = str(datred)
    if len(s) != 8:
        return None
    try:
        return dt.date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def main() -> int:
    from pipelines.orchestration import warn_if_standalone
    warn_if_standalone("A-01 (rada.fetch_cards)")  # loud unless orchestrated
    import argparse
    ap = argparse.ArgumentParser(description="Fetch Rada act cards (T3 / targeted)")
    ap.add_argument("--acts", nargs="+", help="specific nreg(s) — targeted "
                    "collection, NOT added to the general seed; default = SEED_ACTS")
    args = ap.parse_args()
    acts = args.acts or SEED_ACTS

    header("T3 fetch_cards — Rada act cards -> Postgres" + (" (targeted)" if args.acts else ""))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    run_migrations()

    total_editions = 0
    failed_acts: list[str] = []
    deferred = 0
    print(f"Rada budget today: {budget.remaining() / 1e6:.1f} MB left (cap "
          f"{budget.CAP_BYTES / 1e6:.0f} MB)")
    with connect() as conn:
        for nreg in acts:
            # Consult the Rada byte budget (was ignored → each run re-pulled every
            # card uncounted). Defer when the day's budget can't cover another card.
            if not budget.can_spend(CARD_EST_BYTES):
                print(f"  {nreg:14s} DEFERRED — Rada budget {budget.remaining() / 1e6:.1f} MB left")
                deferred += 1
                continue
            q = quote(nreg, safe="")
            try:
                card = get_json(CARD_URL.format(q=q))
            except Exception as exc:  # noqa: BLE001
                print(f"  {nreg:14s} FETCH FAILED: {exc}")
                failed_acts.append(nreg)
                continue

            blob = json.dumps(card, ensure_ascii=False)
            (RAW_DIR / f"{nreg}.json").write_text(blob, encoding="utf-8")
            budget.add(len(blob.encode("utf-8")))

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO acts (nreg, title, type, card_json, fetched_at)
                    VALUES (%s, %s, %s, %s, now())
                    ON CONFLICT (nreg) DO UPDATE
                       SET title = EXCLUDED.title,
                           type = EXCLUDED.type,
                           card_json = EXCLUDED.card_json,
                           fetched_at = now()
                    """,
                    (
                        nreg,
                        card.get("nazva"),
                        str(card["typ"]) if card.get("typ") is not None else None,
                        Json(card),
                    ),
                )

                eds = card.get("eds", []) or []
                inserted = 0
                for e in eds:
                    ed = edition_date(e.get("datred"))
                    if ed is None:
                        continue
                    cur.execute(
                        """
                        INSERT INTO editions (act_nreg, edition_date, pidstava, size, fetched_at)
                        VALUES (%s, %s, %s, %s, now())
                        ON CONFLICT (act_nreg, edition_date) DO UPDATE
                           SET pidstava = EXCLUDED.pidstava,
                               size = EXCLUDED.size,
                               fetched_at = now()
                        """,
                        (nreg, ed, e.get("pidstava") or None, e.get("size")),
                    )
                    inserted += 1
            conn.commit()
            total_editions += inserted
            print(f"  {nreg:14s} title={str(card.get('nazva'))[:44]!r:46s} editions={inserted}")

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM acts")
            n_acts = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM editions")
            n_eds = cur.fetchone()[0]

    print(f"\nDB totals: acts={n_acts}, editions={n_eds}")
    if deferred:
        print(f"DEFERRED (Rada budget): {deferred} card(s) — re-run next day to resume")
    if failed_acts:
        print(f"FETCH FAILURES: {len(failed_acts)} act(s) — {failed_acts}")
    floor_ok = n_eds >= 100
    print(f"Acceptance (editions >= 100): {'PASS' if floor_ok else 'FAIL'}")
    # Honest exit: a swallowed card fetch must not exit green on the cumulative floor;
    # a pure budget defer (nothing fetched, floor already met) is SKIP(2), not OK.
    _summary.emit(ok=total_editions, failed=len(failed_acts))  # bytes: Rada budget-metered
    if failed_acts or not floor_ok:
        return exitcodes.FAIL
    if deferred and total_editions == 0:
        return exitcodes.SKIP
    return exitcodes.OK


if __name__ == "__main__":
    raise SystemExit(main())
