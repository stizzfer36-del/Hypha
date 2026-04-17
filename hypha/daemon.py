"""M1 — asyncio daemon entrypoint.

Role: long-running per-repo process. Owns the event loop. Outlives sessions.
Produces: `DaemonStarted`, `DaemonStopped` heartbeat events.
Consumes: nothing directly — subscribes to the bus once M4 lands. At M1 the
daemon is simply a loop that keeps the CLI-writable ledger alive and prints
new events.
"""

from __future__ import annotations

import asyncio


async def main() -> None:
    raise NotImplementedError(
        "M1: load config, init ledger, append DaemonStarted, idle-poll ledger"
    )


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
