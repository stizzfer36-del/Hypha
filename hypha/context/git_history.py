"""M2 — git archaeology.

Role: expose log and co-change frequency over the repo. Files that change
together are conceptually linked.
Produces: `git_commits(sha, ts, message)` and
`git_commit_files(sha, path)` and `git_co_change(a, b, n)` tables in the
joint-query store.
Consumes: the repo's `.git` via pygit2.

Scope note: stays inside the repo root — no submodule traversal, no upstream
fetches. Pure local read.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import duckdb
import pygit2

SCHEMA = """
CREATE TABLE IF NOT EXISTS git_commits (
    sha TEXT PRIMARY KEY,
    ts BIGINT NOT NULL,
    message TEXT
);
CREATE TABLE IF NOT EXISTS git_commit_files (
    sha TEXT NOT NULL,
    path TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gcf_sha ON git_commit_files(sha);
CREATE INDEX IF NOT EXISTS idx_gcf_path ON git_commit_files(path);
CREATE TABLE IF NOT EXISTS git_co_change (
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    n INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gcc_a ON git_co_change(a);
CREATE INDEX IF NOT EXISTS idx_gcc_b ON git_co_change(b);
"""


def _changed_files(repo: pygit2.Repository, commit: pygit2.Commit) -> list[str]:
    if not commit.parents:
        # Initial commit: every entry in the tree is "added".
        return [e.path for e in _tree_paths(commit.tree)]
    parent = commit.parents[0]
    diff = repo.diff(parent, commit)
    out: set[str] = set()
    for patch in diff:
        delta = patch.delta
        for p in (delta.new_file.path, delta.old_file.path):
            if p:
                out.add(p)
    return sorted(out)


def _tree_paths(tree: pygit2.Tree, prefix: str = ""):
    for entry in tree:
        path = f"{prefix}{entry.name}"
        if isinstance(entry, pygit2.Tree):
            yield from _tree_paths(entry, prefix=path + "/")
        else:
            yield type("E", (), {"path": path})()


class GitHistory:
    def __init__(self, repo_root: Path, duckdb_path: Path):
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.duckdb_path = Path(duckdb_path).expanduser().resolve()
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)

    def rebuild(self, max_commits: int = 5000) -> int:
        repo = pygit2.Repository(str(self.repo_root))
        con = duckdb.connect(str(self.duckdb_path))
        try:
            con.execute(SCHEMA)
            con.execute("DELETE FROM git_commits")
            con.execute("DELETE FROM git_commit_files")
            con.execute("DELETE FROM git_co_change")

            if repo.is_empty:
                return 0

            commit_rows: list[tuple[str, int, str]] = []
            file_rows: list[tuple[str, str]] = []
            pair_counts: dict[tuple[str, str], int] = {}

            count = 0
            for commit in repo.walk(repo.head.target, pygit2.enums.SortMode.TOPOLOGICAL):
                if count >= max_commits:
                    break
                count += 1
                sha = str(commit.id)
                commit_rows.append((sha, int(commit.commit_time), commit.message))
                files = _changed_files(repo, commit)
                for p in files:
                    file_rows.append((sha, p))
                for a, b in combinations(sorted(set(files)), 2):
                    pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1

            if commit_rows:
                con.executemany("INSERT INTO git_commits VALUES (?, ?, ?)", commit_rows)
            if file_rows:
                con.executemany("INSERT INTO git_commit_files VALUES (?, ?)", file_rows)
            if pair_counts:
                con.executemany(
                    "INSERT INTO git_co_change VALUES (?, ?, ?)",
                    [(a, b, n) for (a, b), n in pair_counts.items()],
                )
            return count
        finally:
            con.close()
