"""Build the act link graph (amendment edges) into the links table.

Derived from editions.pidstava (the amending act that produced each edition) — the
core relation graph for the seed acts, already collected by the earlier stages (zero
extra Rada traffic, no URL to hunt). Each distinct (act, amending-act) becomes an
`amended_by` edge. Idempotent (ON CONFLICT DO NOTHING). Broader links.csv relations
can extend this later.

Run:  uv run python -m pipelines.rada.fetch_links
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines import summary as _summary  # noqa: E402
from pipelines.db import connect  # noqa: E402
from pipelines.checks._common import header  # noqa: E402


def main() -> int:
    from pipelines.orchestration import warn_if_standalone
    warn_if_standalone("A-05 (rada.fetch_links)")  # loud unless orchestrated
    header("fetch_links — amendment edge graph (A-05)")
    with connect() as conn:
        with conn.cursor() as cur:
            # A pidstava can name SEVERAL amending acts, comma-separated
            # ('1876-17,1901-17'). Storing the whole list as one `related` made a
            # malformed node; split it so each amending act is its own edge.
            # Purge any legacy comma-nodes first (idempotent).
            cur.execute("DELETE FROM links WHERE rel_type='amended_by' AND related LIKE '%,%'")
            removed = cur.rowcount
            cur.execute(
                """
                INSERT INTO links (act_nreg, related, rel_type, detail, fetched_at)
                SELECT DISTINCT act_nreg, btrim(rel), 'amended_by', NULL, now()
                FROM editions,
                     LATERAL unnest(string_to_array(pidstava, ',')) AS rel
                WHERE pidstava IS NOT NULL AND btrim(rel) <> ''
                ON CONFLICT (act_nreg, related, rel_type) DO NOTHING
                """
            )
            conn.commit()
            if removed:
                print(f"  purged {removed} legacy multi-act node(s) → re-split into per-act edges")
            cur.execute(
                "SELECT a.nreg, count(l.related) FROM acts a "
                "LEFT JOIN links l ON l.act_nreg = a.nreg GROUP BY a.nreg ORDER BY a.nreg"
            )
            rows = cur.fetchall()

    for nreg, n in rows:
        flag = "" if n > 0 else "  (no incoming amendments — pure amending/leaf act)"
        print(f"  {nreg:14s} links={n}{flag}")
    with_links = sum(1 for _, n in rows if n > 0)
    print(f"\nseed acts with >0 links: {with_links}/{len(rows)}")
    _summary.emit(ok=sum(n for _, n in rows), failed=0)  # derived; no network bytes
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
