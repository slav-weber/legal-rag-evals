"""Per-(act, edition) units ledger.

The data-gate's counters are `>=` floors, so a partial deletion (fewer units in one
edition) or an injection into a known edition stays invisible while the total is above
the anchor (slack was already 80 rows). This ledger is the exact manifest
``(act_nreg, edition_date) → units_count``. The gate compares the live DB against it:
a changed/deleted edition is a hard failure; a brand-new edition is expected growth
(NOTE — rebuild the ledger).

Rebuild it after a reparse by calling write() against a live connection.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

LEDGER_PATH = Path(__file__).resolve().parents[1] / "reports" / "units_ledger.json"


def db_entries(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT act_nreg, edition_date::text, count(*) FROM units GROUP BY 1, 2")
        return {f"{a}|{d}": n for a, d, n in cur.fetchall()}


def build(conn) -> dict:
    entries = db_entries(conn)
    return {
        "generated": date.today().isoformat(),
        "acts": len({k.split("|", 1)[0] for k in entries}),
        "editions": len(entries),
        "total_units": sum(entries.values()),
        "entries": dict(sorted(entries.items())),
    }


def write(conn) -> dict:
    led = build(conn)
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(led, ensure_ascii=False, indent=1), encoding="utf-8")
    return led


def load() -> dict | None:
    if not LEDGER_PATH.exists():
        return None
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def diff(ledger_entries: dict, live_entries: dict) -> dict:
    """Pure comparison. `changed_or_deleted` = a hard failure (count drift or an edition
    that vanished); `new_editions` = expected growth (rebuild the ledger)."""
    changed = {k: {"ledger": v, "db": live_entries.get(k)}
               for k, v in ledger_entries.items() if live_entries.get(k) != v}
    new = sorted(set(live_entries) - set(ledger_entries))
    return {"changed_or_deleted": changed, "new_editions": new}
