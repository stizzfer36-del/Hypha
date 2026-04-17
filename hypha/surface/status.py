"""M1 — "what is Hypha doing right now" view.

Role: summarize recent ledger activity + daemon liveness. Backs `hypha
status`.
Produces: plain-text report.
Consumes: ledger reads.
"""

from __future__ import annotations

import time

from hypha.ledger import Ledger


async def render_status(db_path: str) -> str:
    ledger = Ledger(db_path)
    await ledger.init()
    started = await ledger.recent(kind="DaemonStarted", limit=1)
    stopped = await ledger.recent(kind="DaemonStopped", limit=1)
    intents = await ledger.recent(kind="IntentCreated", limit=5)

    now = time.time()
    lines: list[str] = []

    if started:
        age = now - started[0].ts
        last_stop = stopped[0].ts if stopped else 0.0
        alive = started[0].ts > last_stop
        lines.append(
            f"daemon: {'up' if alive else 'down'} — last start "
            f"{age:.0f}s ago ({started[0].id[:8]})"
        )
    else:
        lines.append("daemon: never started")

    lines.append(f"recent intents ({len(intents)}):")
    for e in intents:
        age = now - e.ts
        lines.append(f"  [{age:>5.0f}s] {e.actor}: {e.payload}")

    return "\n".join(lines)
