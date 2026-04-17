"""M2 — tree-sitter AST index.

Role: parse every source file in the repo; emit a symbol graph
(file, symbol name, kind, span) into DuckDB. Re-run on file change.
Produces: `ast_symbols` table in the joint-query store.
Consumes: the repo's working tree.
"""

from __future__ import annotations

from pathlib import Path


class ASTIndex:
    def __init__(self, repo_root: Path, duckdb_path: Path):
        self.repo_root = repo_root
        self.duckdb_path = duckdb_path

    def rebuild(self) -> int:
        raise NotImplementedError("M2: walk repo, parse with tree-sitter, upsert")
