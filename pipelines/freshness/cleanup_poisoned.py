"""Retro-clean — neutralise poisoned source_checks signals written before the probe fix.

Before that fix, a non-2xx probe (e.g. a 403) could still record a non-NULL
signal_value (the sha256('') of an empty seed-hit set), which _freshness would then read as
a live "confirmed unchanged" signal. This script finds such rows — signal_value IS NOT NULL
while the note marks an HTTP 4xx/5xx / block — and NULLs the bogus signal (keeping the row as
an audit record that a probe was attempted). Idempotent: re-running finds nothing.

`collect._freshness` already defends against these at read time (SLO-age + error-note
skip); this closes the hole at the source so the poisoned value can never be trusted again.

    uv run python -m pipelines.freshness.cleanup_poisoned            # report only (dry-run)
    uv run python -m pipelines.freshness.cleanup_poisoned --apply    # NULL the bogus signals

Rule for any future data clean: BEFORE an --apply, capture the PRE-values of every row you
mutate (id + old signal_value/changed/note) into the run report / journal — a clean that only
reports "N rows cleared" is not audit-reversible. The dry-run block below prints those
pre-values by design; copy them into the report before applying.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from pipelines.db import connect, run_migrations  # noqa: E402

# a failed/blocked probe that nonetheless recorded a signal_value = poison.
FIND = ("SELECT id, source_id, checked_at::timestamp(0), signal_value, changed, note "
        "FROM source_checks WHERE signal_value IS NOT NULL "
        "AND note ~* 'HTTP\\s*[45][0-9][0-9]|тимчасово|заблок' ORDER BY checked_at")


def main() -> int:
    ap = argparse.ArgumentParser(description="V1 retro-clean poisoned source_checks signals")
    ap.add_argument("--apply", action="store_true", help="NULL the bogus signals (default: report only)")
    args = ap.parse_args()
    run_migrations()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(FIND)
            rows = cur.fetchall()
        print(f"poisoned source_checks rows (non-NULL signal on a failed/blocked probe): {len(rows)}")
        for rid, src, at, sig, changed, note in rows:
            print(f"  id={rid} {src} {at} signal={sig!r} changed={changed} note={note!r}")
        if not rows:
            print("nothing to clean (idempotent).")
            return 0
        if not args.apply:
            print("\n(dry-run) re-run with --apply to NULL these signals.")
            return 0
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE source_checks SET signal_value = NULL, "
                "note = left(coalesce(note,'') || ' | poisoned signal cleared (V1 retro, R-12/F3)', 500) "
                "WHERE signal_value IS NOT NULL "
                "AND note ~* 'HTTP\\s*[45][0-9][0-9]|тимчасово|заблок' RETURNING id")
            cleared = [r[0] for r in cur.fetchall()]
        conn.commit()
        print(f"\nCLEARED {len(cleared)} poisoned signal(s): ids={cleared}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
