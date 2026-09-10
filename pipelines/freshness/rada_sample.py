"""Capture a REAL r.txt sample + prove the seed matcher live.

An earlier fix made the freshness matcher act-aware (canonical nreg 3633-IX↔3633-20 +
cyrillic 'п'), but its live mechanics were never proven: Rada 403'd for the whole
hardening window, so every run hashed sha256('') and a positive seed match was never
observed — the matching mechanism had not been demonstrated against a live feed. This captures
the actual r.txt feed to DATA_DIR (gitignored — NEVER committed), records a `snapshots`
row (sha256 + bytes), and runs seed_hits() on the REAL feed, printing which seed nregs
are present — so the matcher is demonstrably exercised end-to-end against production
data, not only against the committed fixture. An empty hit set is an HONEST result
(the r.txt recent-changes window rarely contains a seed act).

Run:  uv run python -m pipelines.freshness.rada_sample
"""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from pipelines.db import connect, run_migrations  # noqa: E402
from pipelines.freshness.probe import (  # noqa: E402
    _decode_rada, _get, seed_alias_map, seed_hits)
from pipelines.paths import RAW_DIR, rel  # noqa: E402

RTXT_URL = "https://data.rada.gov.ua/laws/main/r.txt"
SAMPLE_DIR = RAW_DIR / "rada" / "samples"
ARTIFACT_ID = "F1-rada-rtxt"


def main() -> int:
    run_migrations()
    # No redirect-follow on data.rada — a 302 is a UA-lost / anti-DDoS anomaly,
    # not a hop to zakon-HTML; surface it as HTTP 302, don't snapshot an HTML body.
    r = _get(RTXT_URL, "OpenData", follow_redirects=False)
    if r.status_code != 200:
        print(f"HTTP {r.status_code} — r.txt not fetched (Rada window closed / UA lost?)")
        return 1
    text = _decode_rada(r)
    # Same guard as probe.py: a 200 that is not a plain r.txt (stub/captcha) is refused,
    # never snapshotted as a real sample.
    if len(text.strip()) < 50 or "<html" in text[:2000].lower() or not re.search(r"\d+-\d", text):
        print(f"HTTP 200 but body is not a plain r.txt ({len(text)} B) — refused")
        return 1

    raw = r.content
    sha = hashlib.sha256(raw).hexdigest()
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    out = SAMPLE_DIR / f"r_{sha[:12]}.txt"  # raw bytes as served → stable sha; DATA_DIR only
    out.write_bytes(raw)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO snapshots
                   (artifact_id,url,sha256,bytes,kind,http_status,raw_path,fetched_at)
                   VALUES (%s,%s,%s,%s,'rada-rtxt-sample',200,%s,%s)
                   ON CONFLICT (artifact_id,url) DO UPDATE SET sha256=EXCLUDED.sha256,
                   bytes=EXCLUDED.bytes, raw_path=EXCLUDED.raw_path,
                   fetched_at=EXCLUDED.fetched_at""",
                (ARTIFACT_ID, RTXT_URL, sha, len(raw), rel(out),
                 datetime.now(timezone.utc)))
        conn.commit()
        seeds = seed_alias_map(conn)

    present = seed_hits(text, seeds)
    print(f"r.txt sample: {len(raw):,} B, sha {sha[:12]}… → {rel(out)}")
    print(f"snapshots row: artifact={ARTIFACT_ID}, kind=rada-rtxt-sample")
    print(f"seed acts present in LIVE feed: {', '.join(present) if present else 'none'} "
          f"(honest: r.txt is a ~24h recent-changes window)")
    print(f"  matcher exercised over {len(seeds)} alias keys against real production r.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
