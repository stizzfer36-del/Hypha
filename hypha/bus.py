"""M4 — Redis Streams event bus.

Role: coordination fabric. Typed events published/subscribed by agents and
devices. No RPC between components — only events.
Produces: bus adapter; publishes whatever callers publish.
Consumes: redis connection.
"""

from __future__ import annotations

from typing import AsyncIterator


class Bus:
    def __init__(self, url: str | None):
        self.url = url

    async def publish(self, kind: str, payload: dict) -> str:
        raise NotImplementedError("M4: XADD to stream named by kind")

    async def subscribe(self, kinds: list[str]) -> AsyncIterator[dict]:
        raise NotImplementedError("M4: XREAD across streams, yield parsed events")
