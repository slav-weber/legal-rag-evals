"""Daily freshness probe.

Upserts the source list (sources.py) into `source_registry`, polls each source
with a LIGHT probe (conditional GET / metadata JSON / page hash — never a corpus
download), records the signal in `source_checks` (with a changed-vs-previous flag),
and regenerates `reports/freshness.md`. `changed=true` means the source moved →
dependent artifacts may be stale.

Run:  uv run python -m pipelines.freshness.probe

The daily procedure COMMITS reports/freshness.md on every run (not only when it turns 🟢), so
the git trail matches source_checks — intermediate 🟡/⚠ stay on record.
"""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from pipelines.db import connect, run_migrations  # noqa: E402
from pipelines.freshness.sources import SOURCES  # noqa: E402
from pipelines.opendata import auth_headers  # noqa: E402
from pipelines.rada.fetch_cards import SEED_ACTS  # noqa: E402 — act-aware Rada signal

REPO_ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = httpx.Timeout(connect=15.0, read=30.0, write=15.0, pool=15.0)


def _get(url: str, ua: str, extra: dict | None = None, *,
         follow_redirects: bool = True, **kw) -> httpx.Response:
    headers = {"User-Agent": ua}
    if extra:
        headers.update(extra)
    return httpx.get(url, headers=headers, timeout=TIMEOUT,
                     follow_redirects=follow_redirects, **kw)


def _norm_hash(text: str) -> str:
    stripped = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", text))
    return hashlib.sha256(" ".join(stripped.split()).encode("utf-8")).hexdigest()[:16]


def _decode_rada(resp: httpx.Response) -> str:
    """Decode r.txt explicitly. Rada .txt law exports are UTF-8 (the КСУ
    snapshotter sets utf-8 and gets U+FFFD=0), but the r.txt feed declares no charset,
    so httpx may guess wrong and mojibake the cyrillic 'п' in nregs like 560-2024-п —
    which would silently break the seed matcher. Honor an explicit HTTP charset, else
    UTF-8, falling back to windows-1251 on a strict decode error."""
    ct = resp.headers.get("content-type", "")
    m = re.search(r"charset=([\w-]+)", ct, re.I)
    if m:
        try:
            return resp.content.decode(m.group(1), "strict")
        except (LookupError, UnicodeDecodeError):
            pass
    for enc in ("utf-8", "windows-1251"):
        try:
            return resp.content.decode(enc, "strict")
        except UnicodeDecodeError:
            continue
    return resp.content.decode("utf-8", "replace")


def seed_alias_map(conn) -> dict[str, str]:
    """alias nreg -> canonical nreg for the seed acts.

    r.txt uses the *canonical* nreg (card_json.nreg), which for the mobilisation law
    3633-IX is "3633-20" — so matching only SEED_ACTS ("3633-IX") was blind to it
    forever. We match on BOTH spellings but report the canonical, so the signal stays
    stable regardless of which form the feed uses.
    """
    canon: dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT nreg, card_json->>'nreg' FROM acts WHERE nreg = ANY(%s)",
                    (SEED_ACTS,))
        for key, c in cur.fetchall():
            canon[key] = c or key
    amap: dict[str, str] = {}
    for key in SEED_ACTS:
        c = canon.get(key, key)
        amap[key] = c
        amap[c] = c
    return amap


def seed_hits(text: str, alias_to_canon: dict[str, str]) -> list[str]:
    """Canonical seed nregs present in the feed text (token match, both spellings)."""
    hits: set[str] = set()
    for alias, canon in alias_to_canon.items():
        if re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", text):
            hits.add(canon)
    return sorted(hits)


def probe(src: dict, seeds: dict[str, str] | None = None) -> tuple[str | None, str]:
    """Return (signal_value, note). Light request only; raises nothing to caller."""
    kind, url, params = src["probe_kind"], src["url"], src.get("probe_params", {})
    try:
        if kind == "rada_rtxt":
            # Do NOT follow redirects on data.rada — a 302 (UA lost / anti-DDoS
            # routing to zakon-HTML) must read as HTTP 302 probe-fail, not be followed
            # into an HTML body that only the plain-r.txt guard would (later) reject.
            r = _get(url, "OpenData", follow_redirects=False)
            # A non-200, or a 200 whose body is not a real r.txt (empty / an
            # HTML captcha/stub), must NOT yield the sha256('') "no seed acts" signal —
            # that is indistinguishable from an honest "none" and would poison the
            # baseline. Return (None, note) → 🔴 probe-fail instead.
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            text = _decode_rada(r)
            # A 200 with a plausible size but no nreg-like line (a stub / JS
            # captcha that isn't HTML) must not read as an honest "none". Require ≥1 nreg token.
            if (len(text.strip()) < 50 or "<html" in text[:2000].lower()
                    or not re.search(r"\d+-\d", text)):
                return None, f"HTTP 200 but body not a plain r.txt ({len(text)} B, no nreg line)"
            # Act-wide, not source-wide: r.txt (Rada's recent-changes feed) moves for
            # the whole corpus almost daily, so a raw hash cried "changed" every day.
            # Signal only on OUR seed acts — which seed nregs appear in the feed.
            present = seed_hits(text, seeds or {n: n for n in SEED_ACTS})
            sig = hashlib.sha256("|".join(present).encode("utf-8")).hexdigest()[:16]
            return sig, (f"HTTP {r.status_code}, seed acts in feed: "
                         f"{', '.join(present) if present else 'none'}")
        if kind == "ckan":
            r = _get(f"{url}?id={params['package_id']}", "OpenData", extra=auth_headers())
            d = r.json()["result"]
            zips = [x for x in d.get("resources", []) if (x.get("format") or "").upper() == "ZIP"]
            res_lm = zips[0].get("last_modified") if zips else None
            return d.get("metadata_modified"), f"resource last_modified={res_lm}"
        if kind == "hf":
            r = _get(url, "pravo8-freshness")
            # An HF API error (401/404/429) returns JSON without "sha" → the old
            # code emitted sig='' (non-NULL) → 🟡 changed against the real sha, and '' became
            # the baseline (a 2nd false changed on recovery). Treat any non-200 / missing sha
            # as a probe-fail (None), not a signal.
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            sha = (r.json().get("sha") or "")
            if not sha:
                return None, "HTTP 200 but no sha in response"
            # Enforce the declared pin (it used to be dead config) — flag drift off it.
            pin = params.get("pinned_sha")
            off = f" ⚠ off-pin (expected {pin})" if pin and not sha.startswith(pin) else ""
            return sha[:12], f"lastModified={r.json().get('lastModified')}{off}"
        if kind in ("listing_hash", "page_hash"):
            r = _get(url, "Mozilla/5.0")
            if r.status_code != 200:
                # Don't hash the error page (it becomes a bogus baseline that
                # flips the next honest run to 🟡). Report a probe-fail instead.
                return None, f"HTTP {r.status_code} — probe-fail (URL/site issue)"
            enc = params.get("encoding")
            text = r.content.decode(enc, "replace") if enc else r.text
            id_re = params.get("id_regex")
            if id_re:
                # Hash the SET of record IDs on page 1 — robust to markup/date churn
                # (hash the set of IDs, not the raw HTML).
                ids = sorted(set(re.findall(id_re, text)))
                sig = hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:16]
                return sig, f"HTTP 200, {len(ids)} entry-ids"
            return _norm_hash(text), "HTTP 200, page-hash"
        return None, "manual (no machine signal)"
    except Exception as exc:  # noqa: BLE001
        return None, f"PROBE ERROR: {exc}"


def _upsert_sources(conn) -> None:
    import json
    with conn.cursor() as cur:
        for s in SOURCES:
            cur.execute(
                "INSERT INTO source_registry (source_id, name, url, probe_kind, "
                "probe_params, cadence, staleness_slo_days, license) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (source_id) DO UPDATE SET "
                "name=EXCLUDED.name, url=EXCLUDED.url, probe_kind=EXCLUDED.probe_kind, "
                "probe_params=EXCLUDED.probe_params, cadence=EXCLUDED.cadence, "
                "staleness_slo_days=EXCLUDED.staleness_slo_days, license=EXCLUDED.license",
                (s["source_id"], s["name"], s["url"], s["probe_kind"],
                 json.dumps(s.get("probe_params", {})), s["cadence"],
                 s["staleness_slo_days"], s["license"]))
        # GENTLE generator — add/update only, NEVER delete (a DELETE would CASCADE and
        # wipe the source_checks history). REPORT any registry row not in SOURCES as an orphan.
        cur.execute("SELECT source_id FROM source_registry")
        extras = sorted(r[0] for r in cur.fetchall() if r[0] not in {s["source_id"] for s in SOURCES})
        if extras:
            print(f"  ⚠ source_registry has {len(extras)} row(s) NOT in sources.py "
                  f"(orphans — add to sources.py or investigate; NOT auto-deleted): {extras}")
    conn.commit()


def _last_signal(conn, source_id: str) -> str | None:
    # Compare against the last SUCCESSFUL signal, not the last row: a failed probe
    # writes signal_value=NULL, and if that NULL were taken as "prev" the next real
    # signal would compare against NULL → changed=False → the change is masked forever.
    with conn.cursor() as cur:
        cur.execute("SELECT signal_value FROM source_checks "
                    "WHERE source_id=%s AND signal_value IS NOT NULL "
                    "ORDER BY checked_at DESC LIMIT 1", (source_id,))
        row = cur.fetchone()
    return row[0] if row else None


def _write_report(rows: list[dict]) -> Path:
    out = REPO_ROOT / "reports" / "freshness.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Freshness — {date.today().isoformat()}\n",
             "Light polling of the sources. `changed=true` → the source moved, so "
             "dependent artifacts may be stale.\n",
             "| Source | probe | signal | changed | cadence | SLO(days) | status |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        sig = (r["signal"] or "—")
        sig = sig if len(str(sig)) <= 40 else str(sig)[:37] + "…"
        lines.append(f"| {r['source_id']} | {r['probe_kind']} | {sig} | "
                     f"{'🟡 yes' if r['changed'] else 'no'} | {r['cadence']} | "
                     f"{r['slo']} | {r['status']} |")
    lines.append("\n_notes:_\n")
    for r in rows:
        lines.append(f"- **{r['source_id']}**: {r['note']}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    run_migrations()
    report_rows = []
    with connect() as conn:
        _upsert_sources(conn)
        seeds = seed_alias_map(conn)  # canonical + alias nregs (3633-IX ↔ 3633-20)
        for s in SOURCES:
            if s["probe_kind"] == "manual":
                continue  # manual watchers are UPSERTed above but polled by their OWN
                          # collectors (rada_backstop.run below / rada.reachability) — the light
                          # probe must not write a duplicate NULL source_checks row for them.
            prev = _last_signal(conn, s["source_id"])
            sig, note = probe(s, seeds)
            changed = bool(prev is not None and sig is not None and sig != prev)
            with conn.cursor() as cur:
                cur.execute("INSERT INTO source_checks (source_id, signal_value, changed, note) "
                            "VALUES (%s,%s,%s,%s)", (s["source_id"], sig, changed, note))
            conn.commit()
            if sig is None and "manual" not in note:
                status = "🔴 probe-fail"
            elif re.search(r"HTTP [45]\d\d", note):
                status = "🔴 bad-url"
            elif "off-pin" in note:            # pin drift is a STATUS, not just a note
                status = "⚠ off-pin"
            elif changed:
                status = "🟡 changed"
            elif "manual" in note:
                status = "⚪ manual"
            else:
                status = "🟢 ok"
            report_rows.append({"source_id": s["source_id"], "probe_kind": s["probe_kind"],
                                "signal": sig, "changed": changed, "cadence": s["cadence"],
                                "slo": s["staleness_slo_days"], "status": status, "note": note})
            print(f"  {s['source_id']:14s} {status:14s} sig={str(sig)[:30]!r} | {note[:50]}")

        # Second contour — a per-act datred/edcnt backstop closes the r.txt
        # presence-window blind spot. Gate: rada reported changed, or 7 days elapsed.
        # Must never break the light probe → wrapped; degrades on Rada 403.
        rada_changed = any(r["source_id"] == "rada" and r["changed"] for r in report_rows)
        try:
            from pipelines.freshness import rada_backstop
            bs = rada_backstop.run(conn, rada_changed=rada_changed)
            if bs.get("ran"):
                flagged = bool(bs["mismatches"] or bs["changed"])
                bstatus = ("🔴 probe-fail" if bs["signal"] is None
                           else "🟡 changed" if flagged else "🟢 ok")
                report_rows.append({"source_id": "rada-backstop", "probe_kind": "manual",
                                    "signal": bs["signal"], "changed": flagged,
                                    "cadence": "weekly", "slo": 7, "status": bstatus,
                                    "note": bs["note"]})
                print(f"  {'rada-backstop':14s} {bstatus:14s} {bs['note'][:56]}")
            else:
                print(f"  rada-backstop  ⏭ {bs.get('reason')}")
        except Exception as exc:  # noqa: BLE001 — backstop must never break the light probe
            print(f"  rada-backstop  SKIPPED ({exc})")
    path = _write_report(report_rows)
    ok = sum(1 for r in report_rows if r["status"].startswith("🟢"))
    print(f"\nDONE: {len(report_rows)} sources probed, {ok} green → {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
