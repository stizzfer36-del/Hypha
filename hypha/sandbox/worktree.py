"""M3 — per-task git worktree.

Role: every patch attempt runs on its own worktree branch, never the main
checkout. Cleaned up on task completion; preserved on failure for
inspection.
Produces: worktree paths.
Consumes: the repo root and a branch name.

Filesystem isolation only at M3; no syscall / network restrictions — M5
adds firejail for those.
"""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


class WorktreeError(RuntimeError):
    pass


@dataclass
class WorktreeHandle:
    path: Path
    branch: str
    task_id: str


class Worktree:
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.base = self.repo_root / ".hypha" / "worktrees"

    def _run(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *argv],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def create(self, branch: str | None = None) -> WorktreeHandle:
        task_id = uuid.uuid4().hex[:12]
        branch = branch or f"hypha/task-{task_id}"
        self.base.mkdir(parents=True, exist_ok=True)
        path = self.base / task_id
        res = self._run("worktree", "add", "-b", branch, str(path), "HEAD")
        if res.returncode != 0:
            raise WorktreeError(f"git worktree add failed: {res.stderr.strip()}")
        resolved = path.resolve()
        if not str(resolved).startswith(str(self.base.resolve()) + "/") and resolved != self.base.resolve():
            raise WorktreeError(f"worktree escaped sandbox: {resolved}")
        return WorktreeHandle(path=resolved, branch=branch, task_id=task_id)

    def remove(self, handle: WorktreeHandle) -> None:
        res = self._run("worktree", "remove", "--force", str(handle.path))
        if res.returncode != 0:
            # Fall back to prune if the worktree was already gone.
            self._run("worktree", "prune")
