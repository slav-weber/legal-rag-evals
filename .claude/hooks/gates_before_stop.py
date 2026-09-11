"""Stop hook: an agent that changed code cannot finish while a gate is red.

Claude Code runs this before the agent stops. If Python files changed in the working tree and a
deterministic gate fails, the hook exits 2 and prints the reason on stderr, which Claude Code hands
back to the agent instead of letting it stop. With no Python changes, or when this hook has already
blocked once in the same stop (stop_hook_active), it lets the agent stop, so it can never loop.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        event = {}
    if event.get("stop_hook_active"):
        return 0
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8").stdout
    if not any(line.rstrip().endswith(".py") for line in status.splitlines()):
        return 0
    gates = subprocess.run([sys.executable, "-m", "verification.gates"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    if gates.returncode == 0:
        return 0
    failed = "\n".join(line for line in gates.stdout.splitlines()
                       if line.startswith(("FAIL", "RED")))
    print("The gates are red, so the change is not done (AGENTS.md, Definition of done):\n"
          f"{failed}\nRun `uv run python -m verification.gates`, fix the cause, and do not skip "
          "or weaken a test to make it pass.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
