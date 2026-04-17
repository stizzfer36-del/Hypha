"""M1 — asyncio daemon entrypoint.

Role: long-running per-repo process. Owns the event loop. Outlives sessions.
Produces: `DaemonStarted`, `DaemonStopped` heartbeat events.
Consumes: nothing directly — subscribes to the bus once M4 lands. At M1 the
daemon tails the ledger and prints any new events arriving from other
writers (e.g. the CLI), so the human can watch activity in one window while
issuing intents from another.
"""

from __future__ import annotations

import asyncio
import json
import platform
import signal
import socket

from hypha.config import load as load_config
from hypha.events import Kind
from hypha.ledger import Ledger

POLL_INTERVAL = 0.5


async def _emit(ledger: Ledger, kind: str, payload: dict) -> str:
    actor = f"daemon:{socket.gethostname()}"
    return await ledger.append(kind, actor, json.dumps(payload))


async def main() -> None:
    cfg = load_config()
    ledger = Ledger(cfg.db_path)
    await ledger.init()

    started_id = await _emit(
        ledger,
        Kind.DAEMON_STARTED,
        {"host": socket.gethostname(), "python": platform.python_version()},
    )
    print(f"daemon up — db={cfg.db_path} started_id={started_id}")

    stop = asyncio.Event()

    def _on_signal(*_: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            signal.signal(sig, _on_signal)

    last_ts = 0.0
    try:
        while not stop.is_set():
            rows = await ledger.recent(limit=50)
            new = [r for r in rows if r.ts > last_ts]
            for r in sorted(new, key=lambda r: r.ts):
                print(f"{r.ts:.0f} {r.kind:<18} {r.actor:<24} {r.payload}")
            if rows:
                last_ts = max(r.ts for r in rows)
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass
    finally:
        await _emit(ledger, Kind.DAEMON_STOPPED, {"host": socket.gethostname()})
        print("daemon down")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
