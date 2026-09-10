"""Fetch Rada card attachments (fname files) into DATA_DIR.

For each seed act, download every file listed in the card's fname{} (DOCX/RTF/GIF
appendices — for 560-2024-п these are the official відстрочка (deferment) forms)
from data.rada.gov.ua, store under raw/rada/attachments/{nreg}/, hash it (sha256),
and upsert attachments(act_nreg, fname, url, sha256, bytes, raw_path). Idempotent: a
file already on disk is re-hashed and its row refreshed, not re-downloaded.
Budget-metered against the Rada daily cap.

URL: /laws/file/{nreg}/latest/{fname} (302 -> /laws/file/text/NN/{fname}); httpx
follows the redirect. Reads fname from acts.card_json (no card re-fetch).

Run:  uv run python -m pipelines.rada.fetch_attachments
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines import summary as _summary  # noqa: E402
from pipelines.checks._common import get, header  # noqa: E402
from pipelines.db import connect  # noqa: E402
from pipelines.paths import RAW_DIR, rel, sha256_file  # noqa: E402
from pipelines.rada import budget  # noqa: E402

FILE_URL = "https://data.rada.gov.ua/laws/file/{q}/latest/{fname}"


def same_host(request_url: str, final_url: str) -> bool:
    """The attachment 302 is legitimate ONLY within data.rada (/laws/file →
    /laws/file/text). A redirect that lands on a DIFFERENT host (e.g. zakon-HTML via a
    lost-UA / anti-DDoS bounce) must be refused — we opted into follow_redirects, so the
    caller has to verify the destination itself rather than trust any 200."""
    return urlsplit(request_url).hostname == urlsplit(str(final_url)).hostname
ATT_DIR = RAW_DIR / "rada" / "attachments"


def main() -> int:
    from pipelines.orchestration import warn_if_standalone
    warn_if_standalone("A-04 (rada.fetch_attachments)")  # loud unless orchestrated
    header("fetch_attachments — Rada card attachments (A-04 / E-01)")
    print(f"Rada budget: used={budget.used() / 1e6:.1f} MB, remaining={budget.remaining() / 1e6:.1f} MB")
    saved = skipped = deferred = 0
    errors: list[str] = []

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nreg, card_json->'fname' FROM acts ORDER BY nreg")
            acts = cur.fetchall()

        for nreg, fname_obj in acts:
            fnames = sorted(fname_obj.keys()) if isinstance(fname_obj, dict) else []
            if not fnames:
                continue
            out_dir = ATT_DIR / nreg
            out_dir.mkdir(parents=True, exist_ok=True)
            for fname in fnames:
                path = out_dir / fname
                if path.exists() and path.stat().st_size > 0:
                    skipped += 1
                    _upsert(conn, nreg, fname, None, path)
                    continue
                if not budget.can_spend(1_000_000):
                    deferred += 1
                    continue
                url = FILE_URL.format(q=quote(nreg, safe=""), fname=fname)
                # legit same-host 302: /laws/file/{nreg}/latest/… → /laws/file/text/NN/…
                r = get(url, follow_redirects=True)  # explicit opt-in (default now False)
                if not same_host(url, r.url):  # reject a cross-host redirect
                    errors.append(f"{nreg}/{fname}: cross-host redirect to "
                                  f"{urlsplit(str(r.url)).hostname} — refused (not data.rada)")
                    continue
                if r.status_code != 200 or not r.content:
                    errors.append(f"{nreg}/{fname}: HTTP {r.status_code}")
                    print(f"  ! {nreg}/{fname}: HTTP {r.status_code}")
                    continue
                path.write_bytes(r.content)
                budget.add(len(r.content))
                _upsert(conn, nreg, fname, url, path)
                saved += 1
                print(f"  {nreg}/{fname}: {len(r.content):,} bytes")

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM attachments WHERE act_nreg = '560-2024-п'")
            n560 = cur.fetchone()[0]

    print(f"\nDONE: saved={saved}, skipped={skipped}, deferred={deferred}, errors={len(errors)}")
    print(f"560-2024-п attachments in DB: {n560} (expect >= 14 DOCX)")
    for e in errors:
        print(f"  ! {e}")
    _summary.emit(ok=saved, failed=len(errors))  # bytes: Rada budget-metered
    return 1 if errors else 0


def _upsert(conn, nreg: str, fname: str, url: str | None, path: Path) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO attachments (act_nreg, fname, url, sha256, bytes, raw_path, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (act_nreg, fname) DO UPDATE
               SET url = COALESCE(EXCLUDED.url, attachments.url),
                   sha256 = EXCLUDED.sha256, bytes = EXCLUDED.bytes,
                   raw_path = EXCLUDED.raw_path, fetched_at = now()
            """,
            (nreg, fname, url, sha256_file(path), path.stat().st_size, rel(path)),
        )
    conn.commit()


if __name__ == "__main__":
    raise SystemExit(main())
