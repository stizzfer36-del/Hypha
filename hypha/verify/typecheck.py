"""M3 — mypy type-check (if the target repo has mypy configured).

Role: optional verification stage. Skips cleanly when the target has no
mypy config — does not block patches in untyped repos.
Produces: verification result (pass/fail + error list).
Consumes: a worktree path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TypeCheckResult:
    passed: bool
    errors: list[str]
    configured: bool  # False if the repo has no mypy config; not a failure


class TypeChecker:
    async def run(self, cwd: Path) -> TypeCheckResult:
        raise NotImplementedError("M3: detect mypy config, invoke, parse output")
