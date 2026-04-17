"""M3 — pytest runner.

Role: discover and run the target repo's tests inside the worktree;
summarize results into a structured payload for the verifier.
Produces: verification result (pass/fail + per-test diagnostics).
Consumes: a worktree path.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PytestResult:
    passed: bool
    rc: int
    stdout_tail: str
    stderr_tail: str
    ms: int


class PytestRunner:
    def __init__(self, pytest_bin: str = "pytest"):
        self.pytest_bin = pytest_bin

    async def run(self, cwd: Path, selectors: list[str] | None = None) -> PytestResult:
        argv = [self.pytest_bin, "-q"]
        if selectors:
            argv.extend(selectors)
        t0 = time.perf_counter()
        proc = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True, check=False
        )
        ms = int((time.perf_counter() - t0) * 1000)
        # pytest rc 0 = all passed; 5 = no tests collected; otherwise failure.
        passed = proc.returncode == 0
        return PytestResult(
            passed=passed,
            rc=proc.returncode,
            stdout_tail=proc.stdout[-2000:],
            stderr_tail=proc.stderr[-2000:],
            ms=ms,
        )
