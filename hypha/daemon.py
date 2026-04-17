"""Asyncio daemon entrypoint.

Role: long-running per-repo process. Owns the event loop. Outlives sessions.
Produces: `DaemonStarted`, `DaemonStopped` heartbeat events.
Consumes: the ledger and (if configured) the event bus.

Composition:
  * Ledger tailer — prints new events to stdout so a single window shows
    the repo breathing.
  * Supervisor — drains IntentCreated events into plan/code/verify/approve
    pipelines. Auto-accept mode (HYPHA_AUTO_ACCEPT=1) approves every
    passing diff without asking; intended for hands-free canary runs.
  * Heartbeat — if HYPHA_DEVICE_ID is set, registers in the claims DB.

Graceful shutdown on SIGINT/SIGTERM flushes DaemonStopped and releases
claims held by this device.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import signal
import socket
from pathlib import Path

from hypha.config import load as load_config
from hypha.devices.claim import Claim
from hypha.devices.heartbeat import Heartbeat
from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.router import LiveRouter, Router, default_providers
from hypha.supervisor import Supervisor, SupervisorConfig

log = logging.getLogger("hypha.daemon")

POLL_INTERVAL = 0.5


async def _emit(ledger: Ledger, kind: str, payload: dict) -> str:
    actor = f"daemon:{socket.gethostname()}"
    return await ledger.append(kind, actor, json.dumps(payload))


def _build_router(cfg) -> Router:
    providers = default_providers(cfg)
    if providers:
        return LiveRouter(providers)
    # No keys set: return a router whose `call` explains itself. The
    # supervisor will see the error via its exception path and append a
    # VerificationFailed. This keeps the daemon useful as a tail-only
    # process even without credentials.
    return LiveRouter([])


async def _ledger_tail(ledger: Ledger, stop: asyncio.Event) -> None:
    last_ts = 0.0
    while not stop.is_set():
        rows = await ledger.recent(limit=50)
        new = [r for r in rows if r.ts > last_ts]
        for r in sorted(new, key=lambda r: r.ts):
            print(f"{r.ts:.0f} {r.kind:<18} {r.actor:<24} {r.payload}", flush=True)
        if rows:
            last_ts = max(r.ts for r in rows)
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass


def _ask_factory() -> callable:
    """Choose the approval surface.

    * HYPHA_AUTO_ACCEPT=1 — auto-accept passing diffs. Canary use only.
    * default — reject everything; a human must approve via CLI or Telegram.

    (The supervisor writes Verification* regardless; the approval step only
    gates the merge. Rejecting here simply leaves the branch un-merged for
    the human to review out-of-band.)
    """
    if os.environ.get("HYPHA_AUTO_ACCEPT") == "1":
        return lambda _diff: True
    return lambda _diff: False


async def main() -> None:
    cfg = load_config()
    ledger = Ledger(cfg.db_path)
    await ledger.init()

    started_id = await _emit(
        ledger,
        Kind.DAEMON_STARTED,
        {"host": socket.gethostname(), "python": platform.python_version()},
    )
    print(f"daemon up — db={cfg.db_path} started_id={started_id}", flush=True)

    stop = asyncio.Event()

    def _on_signal(*_: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            signal.signal(sig, _on_signal)

    # Optional device heartbeat if the user wants this box on the claims
    # mesh. Shares the claims DB under .hypha/devices.db next to the ledger.
    heartbeat_task: asyncio.Task | None = None
    device_id = os.environ.get("HYPHA_DEVICE_ID")
    devices_db = cfg.db_path.parent / "devices.db"
    if device_id:
        Claim(devices_db, ledger=ledger)  # ensure schema exists
        tags = os.environ.get("HYPHA_DEVICE_TAGS", "dev").split(",")
        hb = Heartbeat(
            device_id=device_id, tags=tags, path=devices_db, ledger=ledger
        )
        heartbeat_task = asyncio.create_task(hb.run())

    # Supervisor drives intents end-to-end.
    sup_cfg = SupervisorConfig(
        repo_root=Path.cwd().resolve(),
        cursor_path=cfg.db_path.parent / "supervisor.cursor",
        run_log_path=cfg.db_path.parent / "runs.db",
        base_branch=os.environ.get("HYPHA_BASE_BRANCH", "main"),
    )
    supervisor = Supervisor(
        ledger=ledger,
        router=_build_router(cfg),
        cfg=sup_cfg,
        ask=_ask_factory(),
    )
    sup_task = asyncio.create_task(supervisor.run())
    tail_task = asyncio.create_task(_ledger_tail(ledger, stop))

    try:
        await stop.wait()
    finally:
        supervisor.stop()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
        tail_task.cancel()
        for t in (sup_task, tail_task, heartbeat_task):
            if t is None:
                continue
            try:
                await asyncio.wait_for(t, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        # Release any claims held by this device on clean shutdown.
        if device_id:
            claim = Claim(devices_db, ledger=ledger)
            # best-effort: release-stale with a 0 timeout will grab anything
            # we own (we haven't beat recently in the shutdown window).
            await claim.release_stale(heartbeat_timeout_s=0.0)
        await _emit(ledger, Kind.DAEMON_STOPPED, {"host": socket.gethostname()})
        print("daemon down", flush=True)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(main())


if __name__ == "__main__":
    run()
