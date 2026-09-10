"""Filesystem locations for raw data snapshots.

Raw data (incl. PII-bearing court texts later) lives ONLY under DATA_DIR — an env
var; default is ``<repo>/data``. DATA_DIR is gitignored and never committed. To
relocate data onto another drive, set DATA_DIR in .env — collectors and DB paths
follow it automatically.

Paths stored in the DB are DATA_DIR-relative POSIX (e.g. ``raw/rada/txt/…``) so
they stay valid regardless of where DATA_DIR points.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("DATA_DIR") or (REPO_ROOT / "data")).resolve()
RAW_DIR = DATA_DIR / "raw"


def rel(path: Path) -> str:
    """DATA_DIR-relative POSIX path for storing in the DB / registry."""
    return path.resolve().relative_to(DATA_DIR).as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
