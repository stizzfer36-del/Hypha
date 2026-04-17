"""M6 — per-agent-run log.

Role: append-only log of every agent run: input context hash, prompt
template id + variant, model id, output, verification result, wall time,
tokens in/out. Drives clustering + variant evaluation.
Produces: `run_log` rows.
Consumes: agent.handle invocations.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    agent TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    model TEXT NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    verification_passed INTEGER NOT NULL,
    ms INTEGER NOT NULL,
    failure_signature TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(ts);
CREATE INDEX IF NOT EXISTS idx_runs_variant ON runs(variant_id);
CREATE INDEX IF NOT EXISTS idx_runs_sig ON runs(failure_signature);
"""


@dataclass
class Run:
    agent: str
    prompt_id: str
    variant_id: str
    model: str
    tokens_in: int
    tokens_out: int
    verification_passed: bool
    ms: int
    failure_signature: Optional[str] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)


class RunLog:
    def __init__(self, path: str | Path):
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(resolved)
        with sqlite3.connect(self.path) as db:
            db.executescript(SCHEMA)

    def append(self, run: Run) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT INTO runs (id, ts, agent, prompt_id, variant_id, model, "
                "tokens_in, tokens_out, verification_passed, ms, failure_signature) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.id,
                    run.ts,
                    run.agent,
                    run.prompt_id,
                    run.variant_id,
                    run.model,
                    run.tokens_in,
                    run.tokens_out,
                    1 if run.verification_passed else 0,
                    run.ms,
                    run.failure_signature,
                ),
            )

    def pass_rate(self, variant_id: str, since_ts: float = 0.0) -> tuple[int, int]:
        with sqlite3.connect(self.path) as db:
            cur = db.execute(
                "SELECT SUM(verification_passed), COUNT(*) FROM runs "
                "WHERE variant_id = ? AND ts >= ?",
                (variant_id, since_ts),
            )
            passed, total = cur.fetchone()
        return int(passed or 0), int(total or 0)

    def daily_pass_rate(self, variant_id: str, days: int = 14) -> list[float]:
        """Return one pass-rate number per day (today - days + 1 .. today).
        Days with zero runs return NaN-like sentinel -1.0 so callers must
        handle them explicitly; no silent zero-fill."""
        now = time.time()
        rates: list[float] = []
        with sqlite3.connect(self.path) as db:
            for i in range(days - 1, -1, -1):
                start = now - (i + 1) * 86400.0
                end = now - i * 86400.0
                cur = db.execute(
                    "SELECT SUM(verification_passed), COUNT(*) FROM runs "
                    "WHERE variant_id = ? AND ts >= ? AND ts < ?",
                    (variant_id, start, end),
                )
                passed, total = cur.fetchone()
                if not total:
                    rates.append(-1.0)
                else:
                    rates.append(int(passed or 0) / int(total))
        return rates

    def recent_failures(self, limit: int = 200) -> list[Run]:
        with sqlite3.connect(self.path) as db:
            cur = db.execute(
                "SELECT id, ts, agent, prompt_id, variant_id, model, tokens_in, "
                "tokens_out, verification_passed, ms, failure_signature "
                "FROM runs WHERE verification_passed = 0 ORDER BY ts DESC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        out: list[Run] = []
        for r in rows:
            out.append(
                Run(
                    id=r[0],
                    ts=r[1],
                    agent=r[2],
                    prompt_id=r[3],
                    variant_id=r[4],
                    model=r[5],
                    tokens_in=r[6],
                    tokens_out=r[7],
                    verification_passed=bool(r[8]),
                    ms=r[9],
                    failure_signature=r[10],
                )
            )
        return out
