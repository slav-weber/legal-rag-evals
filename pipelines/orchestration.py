"""Single point of journaling: the standalone-run guard.

The canonical daily collection path is `collect --all --run`: the orchestrator journals EVERY run
in `ingest_runs` and runs the freshness probe afterwards. A collector launched STANDALONE
(`python -m pipelines.rada.fetch_cards`) bypasses that journal — a legitimate debug and fallback
path, but one that must never pass unnoticed by the operator.

So each orchestrated collector's main() calls `warn_if_standalone()`: silent when the process was
spawned BY the orchestrator (which sets ORCHESTRATED_ENV and journals the run), a loud stderr
warning otherwise. Collectors that write their own `ingest_runs` row are exempt — they are already
noticed by the journal; the warning is for the collectors the orchestrator journals on their behalf.
"""

from __future__ import annotations

import os
import sys

ORCHESTRATED_ENV = "PRAVO8_ORCHESTRATED"


def warn_if_standalone(name: str) -> None:
    """No-op when run under the orchestrator (ORCHESTRATED_ENV=1); else a loud stderr warning."""
    if os.environ.get(ORCHESTRATED_ENV) == "1":
        return  # spawned by the orchestrator — this run IS journaled in ingest_runs
    print(f"!  {name}: STANDALONE run — NOT journaled in ingest_runs. The canonical daily path is "
          f"`python -m pipelines.collect --all --run`, which journals every run and probes source "
          f"freshness. Standalone is a debug and fallback path only.",
          file=sys.stderr)
