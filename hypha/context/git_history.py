"""M2 — git archaeology.

Role: expose blame, log, and co-change frequency over the repo. Files that
change together are conceptually linked.
Produces: `git_commits`, `git_co_change` tables in the joint-query store.
Consumes: the repo's `.git` via pygit2.
"""

from __future__ import annotations

from pathlib import Path


class GitHistory:
    def __init__(self, repo_root: Path, duckdb_path: Path):
        self.repo_root = repo_root
        self.duckdb_path = duckdb_path

    def rebuild(self) -> int:
        raise NotImplementedError(
            "M2: walk commits, record (commit, file, timestamp, message);"
            " derive co-change pairs"
        )
