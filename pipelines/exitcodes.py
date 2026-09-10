"""One honest exit-code convention for every pipeline entry point.

The "exit 0 while errors happened" anti-pattern reappeared in 5 independent scripts after
the first honest-exit fix, because the convention lived only in the files that fix touched.
This is the single source of truth:

  0  OK     — everything that should have happened, happened
  1  FAIL   — any errors or an undercount (fetch failures, validation short, missing data)
  2  SKIP   — a planned skip/defer (budget stop, gate closed) with a NOTE; nothing failed
  3  STALE  — completed but a watched signal says work remains (e.g. a collector added
              nothing while its source reports changed) — visible to cron, not a hard fail

Sites decide SKIP/STALE explicitly; `fail_if` covers the common errors/undercount case.
"""

from __future__ import annotations

OK = 0
FAIL = 1
SKIP = 2
STALE = 3


def fail_if(errors, undercount: bool = False) -> int:
    """FAIL when there are errors (int count or truthy) or an undercount, else OK."""
    return FAIL if (errors or undercount) else OK


# Severity for reducing many codes to one overall code: FAIL dominates, then
# STALE (work remains), then SKIP (deferred), then OK. NB a plain bitwise-OR is WRONG here —
# FAIL(1)|SKIP(2) = 3 would masquerade as STALE.
_SEVERITY = {OK: 0, SKIP: 1, STALE: 2, FAIL: 3}


def worst(codes) -> int:
    """The most severe exit code among many (for a batch/orchestrator run)."""
    return max(codes, key=lambda c: _SEVERITY.get(c, 3), default=OK)
