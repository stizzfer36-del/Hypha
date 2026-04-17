"""M1 — "what is Hypha doing right now" view.

Role: summarize recent ledger activity + daemon liveness. Backs `hypha
status`.
Produces: plain-text report.
Consumes: ledger reads.
"""

from __future__ import annotations


async def render_status(db_path: str) -> str:
    raise NotImplementedError(
        "M1: last-DaemonStarted age, pending intents, recent decisions"
    )
