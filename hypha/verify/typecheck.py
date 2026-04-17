"""M3 — mypy type-check (optional).

Role: run mypy against the worktree only if the repo has mypy configured.
Does not block patches in untyped repos.
Produces: verification result (pass/fail + error list).
Consumes: a worktree path.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

MYPY_CONFIG_NAMES = ("mypy.ini", ".mypy.ini", "pyproject.toml")


def _is_configured(cwd: Path) -> bool:
    if (cwd / "mypy.ini").exists() or (cwd / ".mypy.ini").exists():
        return True
    pp = cwd / "pyproject.toml"
    if pp.exists():
        try:
            return "[tool.mypy]" in pp.read_text()
        except OSError:
            return False
    return False


@dataclass
class TypeCheckResult:
    passed: bool
    configured: bool
    errors: list[str]


class TypeChecker:
    def __init__(self, mypy_bin: str = "mypy"):
        self.mypy_bin = mypy_bin

    async def run(self, cwd: Path) -> TypeCheckResult:
        if not _is_configured(cwd):
            return TypeCheckResult(passed=True, configured=False, errors=[])
        proc = subprocess.run(
            [self.mypy_bin, "."],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        errors = [
            line for line in proc.stdout.splitlines() if ": error:" in line
        ]
        return TypeCheckResult(
            passed=proc.returncode == 0,
            configured=True,
            errors=errors,
        )
