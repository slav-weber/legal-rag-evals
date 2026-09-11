"""The deterministic gates: one list, used by CI and by the seeded-bug benchmark.

Each gate is a command run with the current interpreter from the repository root. CI runs every
gate as its own step (`python -m verification.gates --only <name>`); the seeded-bug benchmark runs
all of them against a copy of the tree with one planted bug. Keeping the list in one place means the
benchmark measures exactly what CI enforces.

Two CI gates need tools this list does not install, so they live only in
`.github/workflows/verify.yml`: the secret scan (gitleaks over the full history) and the dependency
audit (pip-audit over the packages pinned in uv.lock).

    uv run python -m verification.gates                      # every gate
    uv run python -m verification.gates --only lint          # one gate
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD = "eval/data/retrieval_gold_v0.jsonl"


@dataclass(frozen=True)
class Gate:
    name: str
    args: tuple[str, ...]          # arguments after the Python interpreter
    checks: str                    # what a pass proves, in one line


GATES: tuple[Gate, ...] = (
    Gate("unit-tests", ("-m", "unittest", "discover", "-s", "tests", "-q"),
         "the offline test suite passes (model, embeddings and reranker are mocked)"),
    Gate("lint", ("-m", "ruff", "check", "--no-cache", "--output-format", "concise", "."),
         "ruff finds nothing under the rule set in pyproject.toml"),
    Gate("eval-no-llm", ("-m", "eval.harness", "--no-llm", "--etalons", GOLD),
         "the reference questions and the golden corpus validate (format, teeth, bug_ref)"),
    Gate("eval-stub-gate", ("-m", "eval.harness", "--mode", "gate", "--backend", "stub",
                            "--etalons", GOLD),
         "the harness gate is GREEN on the oracle stub: no hallucination, no golden case RED"),
)


@dataclass(frozen=True)
class GateResult:
    name: str
    code: int
    seconds: float
    output: str

    @property
    def passed(self) -> bool:
        return self.code == 0


def gate_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment every gate runs in: UTF-8 I/O on every platform, plus any overrides."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env.update(extra or {})
    return env


def run_gate(gate: Gate, cwd: Path = ROOT, env: dict[str, str] | None = None,
             timeout: float = 600.0) -> GateResult:
    """Run one gate. A timeout counts as a failure (exit code 124), never as a pass."""
    t0 = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, *gate.args], cwd=cwd, env=env,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
        code, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        partial = exc.output or b""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        code, output = 124, f"timed out after {timeout:.0f} s\n{partial}"
    return GateResult(gate.name, code, time.monotonic() - t0, output)


def tail(text: str, lines: int = 40) -> str:
    return "\n".join(text.rstrip().splitlines()[-lines:])


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Run the deterministic gates")
    ap.add_argument("--only", action="append", choices=[g.name for g in GATES],
                    help="run only this gate (repeatable)")
    ap.add_argument("--show-output", action="store_true",
                    help="print every gate's full output, not only the tail of a failure")
    args = ap.parse_args()

    selected = [g for g in GATES if not args.only or g.name in args.only]
    env = gate_env()
    failed: list[str] = []
    for gate in selected:
        result = run_gate(gate, env=env)
        verdict = "PASS" if result.passed else f"FAIL (exit {result.code})"
        print(f"{verdict:14s} {gate.name:15s} {result.seconds:6.1f} s   {gate.checks}")
        if args.show_output:
            print(result.output.rstrip() + "\n")
        elif not result.passed:
            print(tail(result.output) + "\n")
        if not result.passed:
            failed.append(gate.name)
    passed = len(selected) - len(failed)
    print(f"\n{'RED' if failed else 'GREEN'}: {passed}/{len(selected)} gate(s) passed"
          + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
