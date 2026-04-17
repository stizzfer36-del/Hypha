"""M2/M8 — joint context query.

Role: single query across AST and git history (M2); runtime traces and
embeddings layered in at M8. This is the Hypha moat. Neither Cursor nor
Claude Code can issue this query.
Produces: ranked code slices with rationale (which layers matched and why).
Consumes: the DuckDB joint store built by ast_index, git_history,
(M8) runtime_traces, embeddings.

M2 scoring is intentionally simple: per path, sum
  ast_hits        — symbol names matching any query term
  git_msg_hits    — commits touching the path whose message matches terms
  recency_boost   — exp(-age_days / 30) of most-recent commit on the path
and emit top-k slices synthesized from the matching symbol spans.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import duckdb


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


class JointQuery:
    def __init__(self, duckdb_path: Path):
        self.duckdb_path = Path(duckdb_path).expanduser().resolve()

    def query(
        self, text: str, token_cap: int = 4000, limit: int = 10
    ) -> list[Slice]:
        terms = _tokens(text)
        if not terms:
            return []

        like_clauses = " OR ".join(["LOWER(name) LIKE ?"] * len(terms))
        like_params = [f"%{t}%" for t in terms]

        con = duckdb.connect(str(self.duckdb_path), read_only=True)
        try:
            # Collect AST hits: symbols whose names contain any term.
            ast_rows = con.execute(
                f"SELECT path, name, kind, start_line, end_line FROM ast_symbols "
                f"WHERE {like_clauses}",
                like_params,
            ).fetchall()

            # Collect git msg hits: commits whose message contains any term,
            # with the files they touched.
            msg_clauses = " OR ".join(["LOWER(message) LIKE ?"] * len(terms))
            msg_params = [f"%{t}%" for t in terms]
            msg_rows = con.execute(
                f"SELECT gc.sha, gc.ts, gcf.path "
                f"FROM git_commits gc JOIN git_commit_files gcf ON gc.sha = gcf.sha "
                f"WHERE {msg_clauses}",
                msg_params,
            ).fetchall()

            # Recency per path: latest commit ts touching the path.
            recency_rows = con.execute(
                "SELECT gcf.path, MAX(gc.ts) "
                "FROM git_commits gc JOIN git_commit_files gcf ON gc.sha = gcf.sha "
                "GROUP BY gcf.path"
            ).fetchall()
        finally:
            con.close()

        recency: dict[str, float] = {p: float(ts) for p, ts in recency_rows}
        now = time.time()

        scores: dict[str, dict] = {}

        for path, name, kind, a, b in ast_rows:
            s = scores.setdefault(
                path,
                {"ast": [], "git_msgs": set(), "spans": [], "score": 0.0},
            )
            s["ast"].append(name)
            s["spans"].append((int(a), int(b)))
            s["score"] += 1.0

        for sha, ts, path in msg_rows:
            s = scores.setdefault(
                path,
                {"ast": [], "git_msgs": set(), "spans": [], "score": 0.0},
            )
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

        ranked = sorted(scores.items(), key=lambda kv: kv[1]["score"], reverse=True)

        out: list[Slice] = []
        budget = token_cap  # treat as ~ line budget; 4 tokens/line proxy
        for path, s in ranked[:limit]:
            spans = s["spans"] or [(1, 1)]
            spans.sort()
            start = spans[0][0]
            end = max(b for _, b in spans)
            if budget <= 0:
                break
            width = min(end - start + 1, budget)
            out.append(
                Slice(
                    path=path,
                    start_line=start,
                    end_line=start + width - 1,
                    score=round(s["score"], 3),
                    rationale={
                        "ast_symbols": s["ast"],
                        "git_commits": sorted(s["git_msgs"]),
                        "recency_days": s["recency_days"],
                    },
                )
            )
            budget -= width
        return out
