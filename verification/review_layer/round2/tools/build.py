"""Build the second review benchmark: composite items, each a large change with bugs inside it.

    <python> build2.py items2.src.json

items2.src.json:
  {"seed": 20260912, "rev": "129470d", "catalogue": "verification/seeded_bugs/catalogue_v4.py",
   "items": [{"src": "K01", "kind": "bug",   "patch": "clean/K01.patch", "bugs": ["W04", "W11"],
              "description": "..."},
             {"src": "K05", "kind": "clean", "patch": "clean/K05.patch", "bugs": [],
              "description": "..."}]}

Every item is one diff and one tree: the clean change applied, then its bugs planted with the
benchmark's own plant(), so the defects sit inside the large change rather than beside it. Each item
also gets a second tree with the agent rules removed (AGENTS.md, CLAUDE.md, .claude/), for the
reviewer configuration that runs without them. The base tree is `git archive <rev>` without
verification/seeded_bugs/, verification/reports/ and verification/review_layer/, so no tree carries a
catalogue, a report or the earlier benchmark's key.

Items are shuffled with the seed and named r2-item01..; what each one holds is written only to
key2.json, which no reviewer sees.
"""

from __future__ import annotations

import difflib
import io
import json
import random
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path("E:/Web Dev/my-projects/legal-rag-evals")
BENCH = Path(__file__).resolve().parent
RB = BENCH.parent / "rb2"                 # what reviewers may see; key2.json stays in BENCH
TREES, ITEMS = RB / "trees", RB / "items"
EXCLUDE = ("verification/seeded_bugs/", "verification/reports/", "verification/review_layer/")
RULES = ("AGENTS.md", "CLAUDE.md", ".claude")

sys.path.insert(0, str(REPO))
from verification.seeded_bugs.run import load_catalogue, plant  # noqa: E402


def base_tree(rev: str) -> Path:
    data = subprocess.run(["git", "-C", str(REPO), "-c", "core.autocrlf=false", "archive",
                           "--format=tar", rev], capture_output=True, check=True).stdout
    base = TREES / "base"
    shutil.rmtree(base, ignore_errors=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        members = [m for m in tf.getmembers() if not (m.name + "/").startswith(EXCLUDE)]
        tf.extractall(base, members=members, filter="data")
    for path in base.rglob("*"):                                 # one line ending in every tree
        if path.is_file():
            raw = path.read_bytes()
            if b"\r\n" in raw and b"\0" not in raw:
                path.write_bytes(raw.replace(b"\r\n", b"\n"))
    return base


def git_apply(tree: Path, patch: Path) -> None:
    r = subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch)], cwd=tree,
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"!! git apply failed for {patch.name}: {r.stderr.strip()}")


def changed_files(base: Path, tree: Path) -> list[str]:
    out = []
    for path in sorted(tree.rglob("*")):
        if path.is_file():
            rel = path.relative_to(tree).as_posix()
            other = base / rel
            if not other.is_file() or other.read_bytes() != path.read_bytes():
                out.append(rel)
    return out


def whole_diff(base: Path, tree: Path, files: list[str]) -> str:
    out = []
    for rel in files:
        old = (base / rel).read_text(encoding="utf-8").splitlines(keepends=True)
        new = (tree / rel).read_text(encoding="utf-8").splitlines(keepends=True)
        out.append(f"diff --git a/{rel} b/{rel}\n")
        out.extend(difflib.unified_diff(old, new, fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3))
    return "".join(out)


def main() -> int:
    src = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    items = list(src["items"])
    random.Random(src["seed"]).shuffle(items)
    shutil.rmtree(TREES, ignore_errors=True)
    shutil.rmtree(ITEMS, ignore_errors=True)
    ITEMS.mkdir(parents=True)
    base = base_tree(src["rev"])
    catalogue = {b.id: b for b in load_catalogue(REPO / src["catalogue"])}
    public, key = [], {}
    for n, it in enumerate(items, 1):
        name = f"r2-item{n:02d}"
        tree = TREES / name
        shutil.copytree(base, tree)
        git_apply(tree, BENCH / it["patch"])
        clean_files = changed_files(base, tree)
        for bug_id in it["bugs"]:
            plant(catalogue[bug_id], tree)
        files = changed_files(base, tree)
        (ITEMS / f"{name}.patch").write_text(whole_diff(base, tree, files), encoding="utf-8",
                                             newline="\n")
        norules = TREES / f"{name}-norules"
        shutil.copytree(tree, norules)
        for rel in RULES:
            path = norules / rel
            shutil.rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)
        public.append({"item": name, "description": it["description"],
                       "diff": (ITEMS / f"{name}.patch").as_posix(), "tree": tree.as_posix(),
                       "tree_norules": norules.as_posix()})
        key[name] = {"src": it["src"], "kind": it["kind"], "clean_patch": it["patch"],
                     "clean_files": clean_files, "files": files,
                     "bugs": [{"id": b, "title": catalogue[b].title,
                               "files": sorted({e.file for e in catalogue[b].edits})}
                              for b in it["bugs"]]}
        print(f"{name}  {it['kind']:5s}  {it['src']:24s} files {len(files):2d}  bugs "
              f"{', '.join(it['bugs']) or '—'}")
    (BENCH / "items2.json").write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8", newline="\n")
    (BENCH / "key2.json").write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8", newline="\n")
    bugs = sum(len(k["bugs"]) for k in key.values())
    print(f"{len(items)} items, {bugs} planted bugs; base = {src['rev']} without "
          f"{', '.join(EXCLUDE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
