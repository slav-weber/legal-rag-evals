"""Build the review-layer benchmark: one after-tree and one diff per item, blind to its kind.

    <python> build.py items.src.json

items.src.json:
  {"seed": 20260911, "rev": "<git rev>", "items": [
     {"src": "C01", "kind": "clean", "mode": "patch",   "patch": "clean_synthetic/C01.patch",
      "description": "..."},
     {"src": "R1",  "kind": "clean", "mode": "present", "patch": "diffs/clean_R1.patch",
      "description": "..."},
     {"src": "V05", "kind": "bug",   "mode": "catalogue",
      "catalogue": "verification/seeded_bugs/catalogue_v3.py", "description": "..."}]}

mode "patch": the patch is applied to a copy of the base tree. mode "present": the change is
already in the base tree (a real commit); the tree is the base and the diff is that commit's patch,
which must reverse-apply. mode "catalogue": the bug's edits are planted with the benchmark's own
plant() and the diff is generated from the two trees.

The base tree is `git archive <rev>` of the repository without verification/seeded_bugs/ and
verification/reports/, so no tree carries a catalogue or a report that could name a planted bug.
Items are shuffled with the seed and named item01..itemNN; the kind of each item is written only to
key.json, which no reviewer is given.
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
RB = BENCH.parent / "rb"                 # what reviewers may see; key.json stays in BENCH
TREES, ITEMS = RB / "trees", RB / "items"
EXCLUDE = ("verification/seeded_bugs/", "verification/reports/")

sys.path.insert(0, str(REPO))
from verification.seeded_bugs.run import load_catalogue, plant  # noqa: E402


def base_tree(rev: str) -> Path:
    data = subprocess.run(["git", "-C", str(REPO), "-c", "core.autocrlf=false", "archive",
                           "--format=tar", rev], capture_output=True, check=True).stdout
    base = TREES / "base"
    shutil.rmtree(base, ignore_errors=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        members = [m for m in tf.getmembers()
                   if not (m.name + "/").startswith(EXCLUDE)]      # the directories themselves too
        tf.extractall(base, members=members, filter="data")
    for path in base.rglob("*"):                                    # one line ending in every tree
        if path.is_file():
            raw = path.read_bytes()
            if b"\r\n" in raw and b"\0" not in raw:
                path.write_bytes(raw.replace(b"\r\n", b"\n"))
    return base


def git_apply(tree: Path, patch: Path, reverse: bool = False, check: bool = False) -> None:
    args = ["git", "apply", "--whitespace=nowarn"] + (["-R"] if reverse else []) \
        + (["--check"] if check else []) + [str(patch)]
    r = subprocess.run(args, cwd=tree, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"!! git apply {'-R ' if reverse else ''}failed for {patch.name}: "
                         f"{r.stderr.strip()}")


def catalogue_diff(base: Path, tree: Path, files: list[str]) -> str:
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
    catalogues: dict[str, dict] = {}
    public, key = [], {}
    for n, it in enumerate(items, 1):
        name = f"item{n:02d}"
        tree = TREES / name
        shutil.copytree(base, tree)
        info = {"src": it["src"], "kind": it["kind"], "mode": it["mode"]}
        if it["mode"] == "patch":
            patch = BENCH / it["patch"]
            git_apply(tree, patch)
            diff = patch.read_text(encoding="utf-8")
        elif it["mode"] == "present":
            patch = BENCH / it["patch"]
            git_apply(tree, patch, reverse=True, check=True)
            diff = patch.read_text(encoding="utf-8")
        else:
            cat = it["catalogue"]
            if cat not in catalogues:
                catalogues[cat] = {b.id: b for b in load_catalogue(REPO / cat)}
            bug = catalogues[cat][it["src"]]
            plant(bug, tree)
            files = list(dict.fromkeys(e.file for e in bug.edits))
            diff = catalogue_diff(base, tree, files)
            info.update(title=bug.title, story=bug.story, files=files)
        (ITEMS / f"{name}.patch").write_text(diff, encoding="utf-8", newline="\n")
        public.append({"item": name, "description": it["description"],
                       "diff": (ITEMS / f"{name}.patch").as_posix(), "tree": tree.as_posix()})
        key[name] = info
        print(f"{name}  {it['kind']:5s}  {it['src']}")
    (BENCH / "items.json").write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8", newline="\n")
    (BENCH / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8", newline="\n")
    print(f"{len(items)} items; base = {src['rev']} without {', '.join(EXCLUDE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
