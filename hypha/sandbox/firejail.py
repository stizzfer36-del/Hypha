"""M5 — firejail subprocess isolation.

Role: run agent-driven commands (pytest, formatters, scripts) inside a
firejail profile. No network by default. Profile reviewed at M5 commit.
Produces: subprocess results.
Consumes: command + cwd (must be inside the worktree).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Result:
    rc: int
    stdout: str
    stderr: str
    ms: int


class Firejail:
    def __init__(self, profile: Path):
        self.profile = profile

    async def run(self, argv: list[str], cwd: Path, timeout: int = 120) -> Result:
        raise NotImplementedError(
            "M5: exec firejail --profile=... --private=<cwd> -- <argv>,"
            " refuse cwd outside .hypha/worktrees/, capture, timeout"
        )
