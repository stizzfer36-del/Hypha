"""M3 — pytest runner.

Role: discover and run the repo's tests inside the sandbox; summarize
results into a structured payload for the verifier.
Produces: verification result (pass/fail + per-test diagnostics).
Consumes: a worktree path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PytestResult:
    passed: bool
    total: int
    failed_ids: list[str]
    stdout_tail: str
    ms: int


class PytestRunner:
    async def run(self, cwd: Path, selectors: list[str] | None = None) -> PytestResult:
        raise NotImplementedError("M3: invoke pytest under sandbox, parse JUnit xml")
