"""Diff the structural units of an act across its latest editions (v0).

Compares consecutive editions by ``unit_path`` (the stable article-number key)
and reports added / removed / changed units, using the ``{...}`` provenance
markers that appear in the newer edition to explain each change. Output is a
readable Markdown report under ``reports/`` (public legislation only — safe to
commit; no PII).

Run:  uv run python -m pipelines.rada.diff_editions 3543-12 --last 3
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

from pipelines.db import connect  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
# NB: a KIND_ORDER map used to live here, unreferenced, listing 4 of the corpus's kinds — it was
# already missing `chapter` and would have raised KeyError on the first caller that sorted with it.
# A later change added `annex` and `approved` on top. Deleted rather than extended: a lookup table
# nothing reads cannot be kept honest. The authoritative kind list is the CHECK/soft-invariant in
# the chunks migration (020).


def _load(conn, nreg: str, ed) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT unit_path, kind, title, text, inline_markers, ordinal "
            "FROM units WHERE act_nreg = %s AND edition_date = %s",
            (nreg, ed))
        return {r[0]: {"kind": r[1], "title": r[2], "text": r[3],
                       "markers": r[4] or [], "ordinal": r[5]} for r in cur.fetchall()}


def _label(path: str, u: dict) -> str:
    t = (u.get("title") or "").strip()
    return f"`{path}`" + (f" — {t}" if t else "")


def diff_pair(old: dict, new: dict) -> dict:
    old_k, new_k = set(old), set(new)
    added = sorted(new_k - old_k, key=lambda p: new[p]["ordinal"])
    removed = sorted(old_k - new_k, key=lambda p: old[p]["ordinal"])
    changed = sorted(
        (p for p in old_k & new_k if old[p]["text"] != new[p]["text"]),
        key=lambda p: new[p]["ordinal"])
    return {"added": added, "removed": removed, "changed": changed}


def _render_pair(f, old_ed, new_ed, old, new, d) -> None:
    f.append(f"## {old_ed} → {new_ed}\n")
    f.append(f"- added: **{len(d['added'])}**, removed: **{len(d['removed'])}**, "
             f"changed: **{len(d['changed'])}**\n")

    if d["added"]:
        f.append("\n### Added\n")
        for p in d["added"]:
            f.append(f"- {_label(p, new[p])}")
            for m in new[p]["markers"][:2]:
                f.append(f"  \n  ↳ {m}")
            f.append("")
    if d["removed"]:
        f.append("\n### Removed\n")
        for p in d["removed"]:
            f.append(f"- {_label(p, old[p])}")
    if d["changed"]:
        f.append("\n### Changed\n")
        for p in d["changed"]:
            old_m, new_m = set(old[p]["markers"]), set(new[p]["markers"])
            fresh = [m for m in new[p]["markers"] if m not in old_m]
            delta = len(new[p]["text"]) - len(old[p]["text"])
            f.append(f"- {_label(p, new[p])} ({delta:+d} chars)")
            for m in fresh[:3]:
                f.append(f"  \n  ↳ {m}")
    f.append("\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Diff act editions by unit_path (T4 v0)")
    ap.add_argument("nreg")
    ap.add_argument("--last", type=int, default=3, help="how many latest editions")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with connect() as conn:
        with conn.cursor() as cur:
            # in-force only: never diff against a future/placeholder edition as if
            # it were the current law.
            cur.execute(
                "SELECT DISTINCT edition_date FROM units WHERE act_nreg = %s "
                "AND edition_date <= CURRENT_DATE "
                "ORDER BY edition_date DESC LIMIT %s", (args.nreg, args.last))
            eds = [r[0] for r in cur.fetchall()][::-1]  # oldest→newest
        if len(eds) < 2:
            print(f"need >=2 parsed editions of {args.nreg}, have {len(eds)}")
            return 1
        loaded = {ed: _load(conn, args.nreg, ed) for ed in eds}

    lines = [f"# Diff — {args.nreg}: {len(eds)} latest editions\n",
             f"Editions (old→new): {', '.join(str(e) for e in eds)}\n",
             "Units compared by stable `unit_path`; `↳` lines are the `{...}` "
             "amendment markers from the newer edition (provenance). v0.\n"]
    for old_ed, new_ed in zip(eds, eds[1:]):
        d = diff_pair(loaded[old_ed], loaded[new_ed])
        _render_pair(lines, old_ed, new_ed, loaded[old_ed], loaded[new_ed], d)

    out = Path(args.out) if args.out else REPO_ROOT / "reports" / f"diff_{args.nreg}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} ({len(eds)} editions, {len(eds) - 1} pairwise diffs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
