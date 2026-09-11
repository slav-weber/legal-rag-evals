"""Seeded-bug benchmark: plant each catalogued bug in a clean copy of the tree, run every gate and
record which gates catch it.

    uv run python -m verification.seeded_bugs.run                  # full run, writes the report
    uv run python -m verification.seeded_bugs.run --only B01,B07   # a subset, no report
    uv run python -m verification.seeded_bugs.run --no-write       # full run, print only
    uv run python -m verification.seeded_bugs.run \
        --catalogue verification/seeded_bugs/catalogue_heldout.py --label heldout

Method:
1. Copy the working tree (tracked and untracked files; ignored files and earlier reports excluded)
   to a temporary directory.
2. Baseline: every gate must pass on the unmodified copy; a benchmark on a red tree measures noise.
3. For each bug: a fresh copy, the bug's exact find -> replace edits (each must match exactly once),
   then every gate in verification/gates.py, the same list CI runs. Caught = at least one gate
   fails.
4. The catalogue's canary must be caught, otherwise the runner itself is broken and nothing is
   reported.
5. The report (JSON + Markdown) goes to verification/reports/. It names the git revision, a content
   digest of the measured tree and the sha256 of the catalogue, so a number cannot drift away from
   the code and the bugs that produced it. A report never overwrites an earlier one: a second
   report on the same day needs its own --label.

Gates run with API keys and database credentials removed from the environment and with DATA_DIR
pointed at the temporary directory: a planted bug can neither reach a paid API nor write into the
working data.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verification.gates import GATES, gate_env, run_gate, tail  # noqa: E402
from verification.seeded_bugs.catalogue import Bug  # noqa: E402

DEFAULT_CATALOGUE = Path(__file__).resolve().with_name("catalogue.py")
REPORTS = ROOT / "verification" / "reports"
_CREDENTIALS = ("DEEPSEEK_", "OPENAI_", "LLM_API_KEY", "DATABASE_URL", "PGPASSWORD")
_FAILED_TEST = re.compile(r"^(?:FAIL|ERROR): (\S+) \(([^)]+)\)", re.MULTILINE)
_RUFF_CODE = re.compile(r"^\S+:\d+:\d+: ([A-Z]+[0-9]+)", re.MULTILINE)


class CatalogueMismatch(RuntimeError):
    """A find text is missing or ambiguous in the current code: fail loud, never measure a guess."""


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def _digest(data: bytes) -> str:
    """sha256 over LF-normalised bytes, so Windows and Linux checkouts hash the same."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def load_catalogue(path: Path) -> tuple[Bug, ...]:
    """Import a catalogue module by path. It must define BUGS with unique ids and one canary."""
    spec = importlib.util.spec_from_file_location(f"seeded_catalogue_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"!! cannot load the catalogue {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module          # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    bugs = tuple(module.BUGS)
    canaries = [b for b in bugs if b.canary]
    if len(canaries) != 1:
        raise SystemExit(f"!! {path.name}: exactly one canary is required, found {len(canaries)}")
    ids = [b.id for b in bugs]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"!! {path.name}: bug ids are not unique")
    return bugs


def tree_files() -> list[str]:
    listing = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted(p for p in set(listing.split("\0"))
                  if p and not p.startswith("verification/reports/") and (ROOT / p).is_file())


def copy_tree(files: list[str], dest: Path) -> str:
    """Copy the files into dest and return a digest of their paths and contents."""
    tree = hashlib.sha256()
    for rel in files:
        data = (ROOT / rel).read_bytes()
        tree.update(rel.encode("utf-8") + b"\0" + _digest(data).encode("ascii") + b"\n")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return tree.hexdigest()


def plant(bug: Bug, tree: Path) -> None:
    for edit in bug.edits:
        path = tree / edit.file
        text = path.read_text(encoding="utf-8")
        found = text.count(edit.find)
        if found != 1:
            raise CatalogueMismatch(f"{bug.id}: the find text matches {found} time(s) in "
                                    f"{edit.file}; exactly one is required")
        path.write_text(text.replace(edit.find, edit.replace, 1), encoding="utf-8", newline="")


def benchmark_env(data_dir: Path) -> dict[str, str]:
    env = {k: v for k, v in gate_env().items() if not k.upper().startswith(_CREDENTIALS)}
    env["DATA_DIR"] = str(data_dir)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def evidence(gate: str, output: str) -> list[str]:
    """A few concrete signals from a failed gate: failing tests, lint codes or the gate verdict."""
    if gate == "unit-tests":
        return [f"{m.group(1)} ({m.group(2).rsplit('.', 1)[0]})"
                for m in _FAILED_TEST.finditer(output)][:6]
    if gate == "lint":
        return sorted(set(_RUFF_CODE.findall(output)))[:6]
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    marked = [ln for ln in lines if ln.startswith(("!!", "GATE [", "RATCHET"))]
    return (marked or lines[-1:])[:3]


def run_all_gates(tree: Path, env: dict[str, str]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for gate in GATES:
        r = run_gate(gate, cwd=tree, env=env)
        results[gate.name] = {"code": r.code, "seconds": round(r.seconds, 2),
                              "evidence": evidence(gate.name, r.output) if r.code else [],
                              "tail": tail(r.output, 12) if r.code else ""}
    return results


def summarise(counted: list[dict]) -> dict:
    by_area: dict[str, dict[str, int]] = {}
    for r in counted:
        area = by_area.setdefault(r["area"], {"planted": 0, "caught": 0})
        area["planted"] += 1
        area["caught"] += int(r["caught"])
    return {"planted": len(counted), "caught": sum(int(r["caught"]) for r in counted),
            "missed": [r["id"] for r in counted if not r["caught"]],
            "by_area": by_area,
            "caught_by_gate": dict(Counter(g for r in counted for g in r["caught_by"])),
            "only_gate": dict(Counter(r["caught_by"][0] for r in counted
                                      if len(r["caught_by"]) == 1))}


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|")


def render_markdown(meta: dict, summary: dict, bugs: list[dict], canary: dict) -> str:
    n, k = summary["planted"], summary["caught"]
    rate = f"{100 * k / n:.0f} %" if n else "n/a"
    dirty = " + uncommitted changes" if meta["uncommitted_changes"] else ""
    label = f" · {meta['label']}" if meta["label"] else ""
    out = [f"# Seeded-bug benchmark · {meta['date'][:10]}{label}", "",
           f"**The deterministic gates caught {k} of {n} planted bugs ({rate}).** "
           f"The canary ({canary['id']}) was caught by {', '.join(canary['caught_by'])}.", "",
           "| | |", "|---|---|",
           f"| Measured | {meta['date']} · git `{meta['git_head']}`{dirty} · {meta['platform']} · "
           f"Python {meta['python']} |",
           f"| Tree | sha256 `{meta['tree_sha256']}` over {meta['files']} files |",
           f"| Catalogue | `{meta['catalogue']}` · sha256 `{meta['catalogue_sha256']}` |",
           f"| Gates | {' · '.join(meta['gates'])} (the list CI runs: `verification/gates.py`) |",
           "", "## By area", "", "| Area | Planted | Caught |", "|---|---|---|"]
    for area, a in sorted(summary["by_area"].items()):
        out.append(f"| {area} | {a['planted']} | {a['caught']} |")
    out += ["", "## Every bug", "", "| Bug | Area | Planted defect | Caught by | Evidence |",
            "|---|---|---|---|---|"]
    for b in bugs:
        caught = ", ".join(b["caught_by"]) or "**missed**"
        ev = "; ".join(e for g in b["caught_by"] for e in b["gates"][g]["evidence"]) or "—"
        out.append(f"| {b['id']} | {b['area']} | {_cell(b['title'])} | {caught} | {_cell(ev)} |")
    missed = [b for b in bugs if not b["caught"]]
    if missed:
        out += ["", "## Missed", ""]
        out += [f"- **{b['id']}** {_cell(b['title'])}. {b['story']}" for b in missed]
    command = "uv run python -m verification.seeded_bugs.run"
    if meta["catalogue"] != DEFAULT_CATALOGUE.relative_to(ROOT).as_posix():
        command += f" --catalogue {meta['catalogue']}"
    out += ["", "## Reproduce", "", "```bash", "uv sync", command + " --no-write", "```", ""]
    return "\n".join(out)


def report_stem(day: str, label: str) -> str:
    return f"seeded-bugs-{day}" + (f"-{label}" if label else "")


def write_report(meta: dict, baseline: dict, summary: dict, bugs: list[dict],
                 canary: dict) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stem = report_stem(meta["date"][:10], meta["label"])
    public = [{**{k: v for k, v in b.items() if k != "gates"},
               "gates": {g: {"code": r["code"], "seconds": r["seconds"], "evidence": r["evidence"]}
                         for g, r in b["gates"].items()}}
              for b in bugs]
    payload = {"meta": meta,
               "baseline": {g: {"code": r["code"], "seconds": r["seconds"]}
                            for g, r in baseline.items()},
               "canary": {"id": canary["id"], "caught_by": canary["caught_by"]},
               "summary": summary, "bugs": public}
    (REPORTS / f"{stem}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8", newline="\n")
    md = REPORTS / f"{stem}.md"
    md.write_text(render_markdown(meta, summary, bugs, canary), encoding="utf-8", newline="\n")
    return md


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Seeded-bug benchmark over the deterministic gates")
    ap.add_argument("--catalogue", default=DEFAULT_CATALOGUE.relative_to(ROOT).as_posix(),
                    help="catalogue module to plant (a path relative to the repository)")
    ap.add_argument("--label", default="", help="report name suffix, e.g. heldout")
    ap.add_argument("--only", default="", help="comma-separated bug ids; no report is written")
    ap.add_argument("--no-write", action="store_true", help="measure and print, write no report")
    ap.add_argument("--keep", action="store_true", help="keep the temporary trees for inspection")
    args = ap.parse_args()

    catalogue = Path(args.catalogue)
    catalogue = catalogue if catalogue.is_absolute() else ROOT / catalogue
    all_bugs = load_catalogue(catalogue)
    wanted = {s.strip() for s in args.only.split(",") if s.strip()}
    unknown = wanted - {b.id for b in all_bugs}
    if unknown:
        print(f"!! unknown bug id(s): {', '.join(sorted(unknown))}")
        return 2
    selected = [b for b in all_bugs if b.canary or not wanted or b.id in wanted]
    writing = not wanted and not args.no_write
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if writing and (REPORTS / f"{report_stem(today, args.label)}.md").exists():
        print(f"!! a report {report_stem(today, args.label)}.md already exists: pass another "
              f"--label (reports are never overwritten)")
        return 2

    work = Path(tempfile.mkdtemp(prefix="seeded-bugs-"))
    try:
        files = tree_files()
        # provenance of what is measured: taken with the snapshot, not after the run
        snapshot = {"git_head": _git("rev-parse", "--short", "HEAD").strip(),
                    "uncommitted_changes": bool(_git("status", "--porcelain").strip())}
        base = work / "baseline"
        tree_digest = copy_tree(files, base)
        env = benchmark_env(work / "data")

        print(f"baseline: {len(files)} files, every gate on the unmodified tree")
        baseline = run_all_gates(base, env)
        for name, g in baseline.items():
            print(f"  {'PASS' if g['code'] == 0 else 'FAIL'}  {name:15s} {g['seconds']:5.1f} s")
        red = [name for name, g in baseline.items() if g["code"]]
        if red:
            print(f"!! the baseline is RED ({', '.join(red)}); nothing was measured")
            for name in red:
                print(baseline[name]["tail"])
            return 2

        bugs: list[dict] = []
        for bug in selected:
            tree = work / bug.id
            shutil.copytree(base, tree)
            try:
                plant(bug, tree)
            except CatalogueMismatch as exc:
                print(f"!! {exc}")
                return 2
            gates = run_all_gates(tree, env)
            caught_by = [name for name, g in gates.items() if g["code"]]
            bugs.append({"id": bug.id, "area": bug.area, "title": bug.title, "story": bug.story,
                         "canary": bug.canary, "caught": bool(caught_by), "caught_by": caught_by,
                         "gates": gates})
            print(f"{bug.id}  {'CAUGHT' if caught_by else 'MISSED'}  {bug.title}")
            for name in caught_by:
                signal = ", ".join(gates[name]["evidence"]) or f"exit {gates[name]['code']}"
                print(f"        {name}: {signal}")
            if not args.keep:
                shutil.rmtree(tree, ignore_errors=True)

        canary = next(b for b in bugs if b["canary"])
        if not canary["caught"]:
            print("!! the canary was not caught: the runner does not see planted edits; "
                  "nothing is reported")
            return 2
        counted = [b for b in bugs if not b["canary"]]
        summary = summarise(counted)
        if counted:
            print(f"\ncaught {summary['caught']} of {summary['planted']} planted bugs "
                  f"({100 * summary['caught'] / summary['planted']:.0f} %)")
        if not writing:
            return 0
        meta = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "label": args.label,
                **snapshot,
                "tree_sha256": tree_digest, "files": len(files),
                "catalogue": catalogue.relative_to(ROOT).as_posix(),
                "catalogue_sha256": _digest(catalogue.read_bytes()),
                "python": platform.python_version(), "platform": platform.system(),
                "gates": [g.name for g in GATES]}
        report = write_report(meta, baseline, summary, counted, canary)
        print(f"report: {report.relative_to(ROOT).as_posix()}")
        return 0
    finally:
        if args.keep:
            print(f"trees kept in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
