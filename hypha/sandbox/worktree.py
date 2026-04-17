"""M3 — per-task git worktree.

Role: every patch attempt runs on its own worktree branch, never the main
checkout. Cleaned up on task completion; preserved on failure for
inspection.
Produces: worktree paths.
Consumes: the repo root and a branch name.
"""

from __future__ import annotations

from pathlib import Path


class Worktree:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def create(self, branch: str) -> Path:
        raise NotImplementedError("M3: git worktree add under .hypha/worktrees/<id>")

    def remove(self, path: Path) -> None:
        raise NotImplementedError("M3: git worktree remove; keep branch until merged")
