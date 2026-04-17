"""M2/M8 — joint context query.

Role: single query across AST, git history, runtime traces, and embeddings.
This is the Hypha moat. Neither Cursor nor Claude Code can issue this query.
Produces: ranked code slices with rationale (which layers matched and why).
Consumes: the DuckDB joint store built by ast_index, git_history,
runtime_traces, embeddings.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Slice:
    path: str
    start_line: int
    end_line: int
    score: float
    rationale: dict  # which layer(s) matched: ast, git, runtime, embedding


class JointQuery:
    def __init__(self, duckdb_path: Path):
        self.duckdb_path = duckdb_path

    def query(self, text: str, token_cap: int = 4000) -> list[Slice]:
        raise NotImplementedError(
            "M2: AST+git joint rank, recency-weighted decay, token-cap per slice."
            " M8: add runtime + embedding layers."
        )
