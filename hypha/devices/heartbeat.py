"""M7 — device heartbeat.

Role: each box running the daemon publishes a `DeviceHeartbeat` with its
capability tags (`always-on`, `gpu`, `dev`, `mobile-surface`). Stale
heartbeats release claims held by that device.
Produces: `DeviceHeartbeat`.
Consumes: device self-identification (hostname + tags).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from hypha.events import Kind
from hypha.ledger import Ledger


class Heartbeat:
    def __init__(
        self,
        device_id: str,
        tags: list[str],
        path: str | Path,
        ledger: Optional[Ledger] = None,
        interval_s: float = 15.0,
    ):
        self.device_id = device_id
        self.tags = list(tags)
        self.path = str(Path(path).expanduser().resolve())
        self.ledger = ledger
        self.interval_s = interval_s
        self._stop = asyncio.Event()

    def beat_once(self) -> float:
        now = time.time()
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT INTO heartbeats (device_id, last_seen_ts, tags) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(device_id) DO UPDATE SET "
                "last_seen_ts = excluded.last_seen_ts, tags = excluded.tags",
                (self.device_id, now, json.dumps(sorted(self.tags))),
            )
        return now

    async def run(self) -> None:
        while not self._stop.is_set():
            now = self.beat_once()
            if self.ledger is not None:
                await self.ledger.append(
                    Kind.DEVICE_HEARTBEAT,
                    f"device:{self.device_id}",
                    json.dumps({"tags": self.tags, "ts": now}),
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_s)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
