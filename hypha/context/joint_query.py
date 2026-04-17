"""M2/M8 — joint context query.

Role: single query across AST, git history, runtime traces, and embeddings.
This is the Hypha moat. Neither Cursor nor Claude Code can issue this query.
Produces: ranked code slices with rationale (which layers matched and why).
Consumes: the DuckDB joint store built by ast_index, git_history,
runtime_traces, embeddings.

Scoring is additive across layers and intentionally simple. Layers that are
absent (empty tables) contribute zero — so a v1 store (M2-only) gets v1
behavior and a v2 store (with runtime + embeddings) gets the full signal.

Per-path score components:
  ast_hits        — symbol names matching any query term           (+1.0 each)
  git_msg_hits    — commits touching path w/ matching message      (+0.5 each)
  recency_boost   — exp(-age_days / 30) on latest commit ts        (+0..1)
  runtime_recent  — recent span on the path, weighted by ok/!ok    (+0..1.5)
  embedding_sim   — cosine similarity of query vs indexed vectors  (+0..1)
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from hypha.context.embeddings import Embeddings, HashEncoder


@dataclass
class Slice:
    path: str
    start_line: int
    end_line: int
    score: float
    rationale: dict = field(default_factory=dict)


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    try:
        con.execute(f"SELECT 1 FROM {name} LIMIT 0")
        return True
    except duckdb.CatalogException:
        return False


class JointQuery:
    def __init__(self, duckdb_path: Path, embeddings: Embeddings | None = None):
        self.duckdb_path = Path(duckdb_path).expanduser().resolve()
        # Embeddings are managed externally but may be wired in for M8 scoring.
        self._embeddings = embeddings

    def query(
        self, text: str, token_cap: int = 4000, limit: int = 10
    ) -> list[Slice]:
        terms = _tokens(text)
        if not terms:
            return []

        con = duckdb.connect(str(self.duckdb_path), read_only=True)
        try:
            rows_ast = []
            msg_rows: list[tuple] = []
            recency_rows: list[tuple] = []
            runtime_rows: list[tuple] = []

            if _has_table(con, "ast_symbols"):
                like_clauses = " OR ".join(["LOWER(name) LIKE ?"] * len(terms))
                like_params = [f"%{t}%" for t in terms]
                rows_ast = con.execute(
                    f"SELECT path, name, kind, start_line, end_line FROM ast_symbols "
                    f"WHERE {like_clauses}",
                    like_params,
                ).fetchall()

            if _has_table(con, "git_commits") and _has_table(con, "git_commit_files"):
                msg_clauses = " OR ".join(["LOWER(message) LIKE ?"] * len(terms))
                msg_params = [f"%{t}%" for t in terms]
                msg_rows = con.execute(
                    f"SELECT gc.sha, gc.ts, gcf.path "
                    f"FROM git_commits gc JOIN git_commit_files gcf ON gc.sha = gcf.sha "
                    f"WHERE {msg_clauses}",
                    msg_params,
                ).fetchall()
                recency_rows = con.execute(
                    "SELECT gcf.path, MAX(gc.ts) "
                    "FROM git_commits gc JOIN git_commit_files gcf ON gc.sha = gcf.sha "
                    "GROUP BY gcf.path"
                ).fetchall()

            if _has_table(con, "runtime_spans"):
                runtime_rows = con.execute(
                    "SELECT path, MAX(ts) as latest, "
                    "SUM(CASE WHEN ok THEN 0 ELSE 1 END) as fails, "
                    "COUNT(*) as total "
                    "FROM runtime_spans GROUP BY path"
                ).fetchall()
        finally:
            con.close()

        recency: dict[str, float] = {p: float(ts) for p, ts in recency_rows}
        now = time.time()

        scores: dict[str, dict] = {}

        def _bucket(path: str) -> dict:
            return scores.setdefault(
                path,
                {
                    "ast": [],
                    "git_msgs": set(),
                    "spans": [],
                    "score": 0.0,
                    "runtime": None,
                    "embedding_sim": None,
                },
            )

        for path, name, kind, a, b in rows_ast:
            s = _bucket(path)
            s["ast"].append(name)
            s["spans"].append((int(a), int(b)))
            s["score"] += 1.0

        for sha, ts, path in msg_rows:
            s = _bucket(path)
            s["git_msgs"].add(sha[:8])
            s["score"] += 0.5

        for path, s in scores.items():
            ts = recency.get(path)
            if ts:
                age_days = max((now - ts) / 86400.0, 0.0)
                boost = math.exp(-age_days / 30.0)
                s["score"] += boost
                s["recency_days"] = age_days
            else:
                s["recency_days"] = None

        # Runtime-traces layer (M8): recent failures on a path bump it.
        for path, latest, fails, total in runtime_rows:
            if path not in scores:
                continue  # only boost paths the other layers already flagged
            age_days = max((now - float(latest)) / 86400.0, 0.0)
            recency_w = math.exp(-age_days / 7.0)
            fail_w = 1.0 if total and fails >= total / 2 else 0.5
            boost = recency_w * fail_w
            scores[path]["score"] += boost
            scores[path]["runtime"] = {
                "latest_days": age_days,
                "fails": int(fails or 0),
                "total": int(total or 0),
            }

        # Embedding layer (M8): cosine similarity on indexed entries referencing
        # file paths via source_id. Strong similarity surfaces paths on its
        # own; weak similarity only re-ranks.
        EMB_SURFACE_THRESHOLD = 0.25
        if self._embeddings is not None:
            top = self._embeddings.topk(text, k=50)
            for kind, sid, sim in top:
                if kind != "file" or sim <= 0:
                    continue
                if sid in scores or sim >= EMB_SURFACE_THRESHOLD:
                    s = _bucket(sid)
                    s["score"] += float(sim)
                    s["embedding_sim"] = round(float(sim), 3)

        ranked = sorted(scores.items(), key=lambda kv: kv[1]["score"], reverse=True)

        out: list[Slice] = []
        budget = token_cap
        for path, s in ranked[:limit]:
            spans = s["spans"] or [(1, 1)]
            spans.sort()
            start = spans[0][0]
            end = max(b for _, b in spans)
            if budget <= 0:
                break
            width = min(end - start + 1, budget)
            rationale = {
                "ast_symbols": s["ast"],
                "git_commits": sorted(s["git_msgs"]),
                "recency_days": s.get("recency_days"),
                "runtime": s.get("runtime"),
                "embedding_sim": s.get("embedding_sim"),
            }
            out.append(
                Slice(
                    path=path,
                    start_line=start,
                    end_line=start + width - 1,
                    score=round(s["score"], 3),
                    rationale=rationale,
                )
            )
            budget -= width
        return out
