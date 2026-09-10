"""Honest Rada open-data reachability probe (the watcher signal, redefined).

The 2026-07-09 "migration" false alarm came from a naive `200 → open` gate: a browser
UA (or a UA lost on a redirect hop) makes data.rada 302-route non-opendata clients to
the human site zakon.rada.gov.ua (HTML), and `follow_redirects=True` turned that into a
misleading 200. This encodes the CORRECT signal: ALWAYS send UA
'OpenData', NEVER follow redirects, and classify by content, not bare status:

    GREEN   200 + application/json + body starts with '{'  → API alive → execute
    YELLOW  403                                             → TEMPORARY anti-DDoS IP block;
                                                              back off in HOURS (aggressive
                                                              retry self-worsens the block)
    RED     302 (with the correct UA) / 200 text/html       → genuine routing/migration
                                                              anomaly → human look
    ERROR   timeout / 5xx / connect fail / other            → transient → retry politely

A CNAME change (data.rada → other) counts as RED too, but that is an infra/DNS check
outside a single HTTP probe — verify manually if this probe ever reports RED.

Run:  uv run python -m pipelines.rada.reachability
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines import exitcodes  # noqa: E402

GREEN, YELLOW, RED, ERROR = "GREEN", "YELLOW", "RED", "ERROR"
PROBE_URL = "https://data.rada.gov.ua/laws/card/1404-19.json"
UA = "OpenData"
SOURCE_ID = "rada-reachability"

# GREEN → OK(0); YELLOW/ERROR → SKIP(2) (retry later, hours for YELLOW); RED → FAIL(1).
_EXIT = {GREEN: exitcodes.OK, YELLOW: exitcodes.SKIP, ERROR: exitcodes.SKIP, RED: exitcodes.FAIL}


def classify(resp: httpx.Response) -> tuple[str, str]:
    """Map an UNfollowed data.rada response (UA 'OpenData') to (signal, reason)."""
    ct = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if resp.status_code == 200:
        head = resp.content[:64].lstrip()
        if ct == "application/json" and head[:1] == b"{":
            return GREEN, "200 application/json + JSON body — API alive"
        return RED, f"200 but content-type={ct or '?'} (not opendata JSON) — routing anomaly"
    if resp.status_code == 403:
        return YELLOW, "403 — temporary anti-DDoS IP block; back off in HOURS"
    if resp.is_redirect:
        loc = resp.headers.get("location", "?")
        return RED, f"{resp.status_code} redirect to {loc} with UA '{UA}' — routing anomaly"
    return ERROR, f"HTTP {resp.status_code} — transient"


def probe(url: str = PROBE_URL, timeout: float = 25.0) -> tuple[str, str]:
    """Return (signal, reason). Sends UA 'OpenData'; NEVER follows redirects."""
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=timeout,
                      follow_redirects=False)
    except Exception as exc:  # noqa: BLE001
        return ERROR, f"{type(exc).__name__}: {exc}"
    return classify(r)


def persist(conn, sig: str, reason: str) -> bool:
    """Record the probe in source_checks so a GREEN/RED is on the audit trail,
    not a transient [LIVE] print. Returns changed-vs-last-signal.

    The source_registry row for 'rada-reachability' is owned by the SINGLE writer
    (probe._upsert_sources via freshness/sources.py); the inline self-INSERT here was removed.
    This watcher writes ONLY source_checks."""
    with conn.cursor() as cur:
        cur.execute("SELECT signal_value FROM source_checks WHERE source_id=%s "
                    "AND signal_value IS NOT NULL ORDER BY checked_at DESC LIMIT 1", (SOURCE_ID,))
        row = cur.fetchone()
        prev = row[0] if row else None
        changed = bool(prev is not None and prev != sig)
        cur.execute("INSERT INTO source_checks (source_id, signal_value, changed, note) "
                    "VALUES (%s,%s,%s,%s)", (SOURCE_ID, sig, changed, f"{sig}: {reason}"))
    conn.commit()
    return changed


def main() -> int:
    from pipelines.db import connect, run_migrations
    sig, reason = probe()
    persisted = ""
    try:
        run_migrations()
        with connect() as conn:
            changed = persist(conn, sig, reason)
        persisted = f"  [recorded in source_checks{'; CHANGED vs last' if changed else ''}]"
    except Exception as exc:  # noqa: BLE001 — a DB hiccup must not hide the signal
        persisted = f"  [NOT recorded: {type(exc).__name__}]"
    print(f"rada-reachability: {sig} — {reason}{persisted}")
    return _EXIT[sig]


if __name__ == "__main__":
    raise SystemExit(main())
