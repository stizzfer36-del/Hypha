"""M7 — device heartbeat.

Role: each box running the daemon publishes a `DeviceHeartbeat` with its
capability tags (`always-on`, `gpu`, `dev`, `mobile-surface`). Stale
heartbeats release claims held by that device.
Produces: `DeviceHeartbeat`.
Consumes: device self-identification (hostname + tags).
"""

from __future__ import annotations


class Heartbeat:
    def __init__(self, device_id: str, tags: list[str]):
        self.device_id = device_id
        self.tags = tags

    async def run(self) -> None:
        raise NotImplementedError("M7: publish heartbeat every N seconds")
