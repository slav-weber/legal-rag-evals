"""COLLECT-SUMMARY — the machine-readable line a collector prints so the orchestrator can
journal HONEST counts, instead of scraping free-form stdout or hardcoding items_ok=0 /
items_failed=1 on the failure path.

Contract: a collector's main() calls `emit(ok=, failed=, nbytes=, marked=)` as its final
output, on BOTH the success and the failure path (before returning its exit code). The
orchestrator calls `parse(stdout)` to recover {ok, failed, bytes, marked}; a MISSING line →
None, and the orchestrator then appends "[no COLLECT-SUMMARY: unmeasured]" to the run note and
falls back to items_failed=1 (so an unmeasured collector is visible, not silently 0-counted).
`ok`/`failed` are the collector's OWN item counts; `marked` = rows marked terminal this
run; `bytes` is real WIRE bytes for non-Rada hosts (Rada hosts are byte-metered by the
orchestrator via budget.used(), so they may emit bytes=0).
"""

from __future__ import annotations

import re

# `marked` is optional for back-compat (a collector that doesn't mark rows omits it → 0).
_RE = re.compile(r"COLLECT-SUMMARY\s+ok=(\d+)\s+failed=(\d+)\s+bytes=(\d+)(?:\s+marked=(\d+))?")


def emit(ok: int = 0, failed: int = 0, nbytes: int = 0, marked: int = 0) -> None:
    print(f"COLLECT-SUMMARY ok={int(ok)} failed={int(failed)} bytes={int(nbytes)} marked={int(marked)}")


def parse(stdout: str | None) -> dict | None:
    """Recover the LAST COLLECT-SUMMARY line from a collector's stdout, or None if absent."""
    if not stdout:
        return None
    last = None
    for last in _RE.finditer(stdout):
        pass
    if last is None:
        return None
    return {"ok": int(last.group(1)), "failed": int(last.group(2)), "bytes": int(last.group(3)),
            "marked": int(last.group(4)) if last.group(4) else 0}
