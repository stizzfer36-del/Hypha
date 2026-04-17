"""M8 — semantic embedding index.

Role: embeddings over docstrings, commit messages, and ledger entries. The
index is repo-local — no embeddings leave the host.
Produces: `embeddings(source_kind, source_id, text, vector)` table.
Consumes: files, commit messages, and ledger rows.

The encoder is injectable. By default we ship `HashEncoder` — a tiny,
deterministic, low-dim encoder with no external weights — so tests and
zero-dependency installs work out of the box. Upgrade to sentence-
transformers / MiniLM by instantiating `MiniLMEncoder` and passing it to
`Embeddings` when real semantic similarity matters. The protocol is the
interface; the MoniLM wrapper is a thin adapter.
"""

from __future__ import annotations

import array
import hashlib
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import duckdb


SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    source_kind TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    text        TEXT NOT NULL,
    vector      BLOB NOT NULL,
    dim         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_emb_src ON embeddings(source_kind);
"""


class Encoder(Protocol):
    dim: int

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass
class HashEncoder:
    """Deterministic, reproducible hash-bucket encoder.

    Not a real semantic encoder — it maps token hashes into a small fixed
    vector and L2-normalizes. Good enough for M8 plumbing + tests; swap in
    a real model before trusting semantic queries in production.
    """

    dim: int = 64

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            vec = [0.0] * self.dim
            for tok in t.lower().split():
                h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest()[:8], 16)
                vec[h % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


class MiniLMEncoder:
    """Optional adapter over sentence-transformers. Import-guarded so the
    rest of the package has no hard dep on torch.
    """

    dim: int

    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as e:
            raise ImportError(
                "MiniLMEncoder requires `pip install sentence-transformers`. "
                "Use HashEncoder for a zero-dep default."
            ) from e
        self._model = SentenceTransformer(model)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.encode(list(texts))]


def _to_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _from_blob(blob: bytes, dim: int) -> list[float]:
    return list(array.array("f", blob))[:dim]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


class Embeddings:
    def __init__(self, duckdb_path: Path, encoder: Encoder | None = None):
        self.duckdb_path = Path(duckdb_path).expanduser().resolve()
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        self.encoder: Encoder = encoder or HashEncoder()
        con = duckdb.connect(str(self.duckdb_path))
        try:
            con.execute(SCHEMA)
        finally:
            con.close()

    def upsert(self, items: list[tuple[str, str, str]]) -> int:
        """items = [(source_kind, source_id, text), ...]"""
        if not items:
            return 0
        texts = [t for _, _, t in items]
        vecs = self.encoder.encode(texts)
        rows = [
            (kind, sid, text, _to_blob(vec), self.encoder.dim)
            for (kind, sid, text), vec in zip(items, vecs)
        ]
        con = duckdb.connect(str(self.duckdb_path))
        try:
            # No primary key on (kind, id) — callers reset per rebuild; keeps
            # this module storage-only without implicit delete semantics.
            con.executemany(
                "INSERT INTO embeddings (source_kind, source_id, text, vector, dim) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
        finally:
            con.close()
        return len(rows)

    def reset(self) -> None:
        con = duckdb.connect(str(self.duckdb_path))
        try:
            con.execute("DELETE FROM embeddings")
        finally:
            con.close()

    def topk(self, query: str, k: int = 10) -> list[tuple[str, str, float]]:
        """Returns (source_kind, source_id, score). Cosine over indexed vectors.
        Read-only connection so multiple processes can query concurrently."""
        qv = self.encoder.encode([query])[0]
        con = duckdb.connect(str(self.duckdb_path), read_only=True)
        try:
            rows = con.execute(
                "SELECT source_kind, source_id, vector, dim FROM embeddings"
            ).fetchall()
        finally:
            con.close()
        scored: list[tuple[str, str, float]] = []
        for kind, sid, blob, dim in rows:
            v = _from_blob(bytes(blob), int(dim))
            scored.append((kind, sid, _cosine(qv, v)))
        scored.sort(key=lambda t: t[2], reverse=True)
        return scored[:k]
