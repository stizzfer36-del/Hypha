"""M6 — per-agent-run log.

Role: append-only log of every agent run: input context hash, prompt
template id + variant, model id, output, verification result, wall time,
tokens in/out. Drives clustering + variant evaluation.
Produces: `run_log` rows.
Consumes: agent.handle invocations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Run:
    id: str
    ts: float
    agent: str
    prompt_id: str
    variant_id: str
    model: str
    tokens_in: int
    tokens_out: int
    verification_passed: bool
    ms: int


class RunLog:
    async def append(self, run: Run) -> None:
        raise NotImplementedError("M6: persist run; used by clustering + canary")
