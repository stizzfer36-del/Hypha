"""M8 — semantic embedding index.

Role: MiniLM embeddings over docstrings, commit messages, issue discussions,
and ledger entries. Index is repo-local — no embeddings leave the host.
Produces: `embeddings` table (id, source, vector).
Consumes: files, commit messages, and ledger rows.
"""

from __future__ import annotations

from pathlib import Path


class Embeddings:
    def __init__(self, duckdb_path: Path, model: str = "all-MiniLM-L6-v2"):
        self.duckdb_path = duckdb_path
        self.model = model

    def rebuild(self) -> int:
        raise NotImplementedError(
            "M8: encode source corpus with sentence-transformers, store vectors"
        )

    def topk(self, query: str, k: int = 10) -> list[dict]:
        raise NotImplementedError("M8: encode query, cosine-similarity top-k")
