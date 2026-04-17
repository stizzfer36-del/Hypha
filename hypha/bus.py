"""M4 — Redis Streams event bus.

Role: coordination fabric. Typed events published/subscribed by agents and
devices. No RPC between components — only events.
Produces: bus adapter; publishes whatever callers publish.
Consumes: redis connection.

Events are serialized as Redis Stream entries with a single field "payload"
holding JSON. One stream per event kind — simpler than one-stream-many-kinds
and matches natural consumer subscription patterns.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import AsyncIterator

import redis.asyncio as aioredis


PAYLOAD_CAP_BYTES = 65_536  # reject oversized events at the boundary


@dataclass
class BusEvent:
    kind: str
    id: str
    payload: dict


def _stream_name(kind: str) -> str:
    return f"hypha:ev:{kind}"


class Bus:
    def __init__(self, url: str | None):
        """`url=None` works only for explicit in-memory tests; pass an
        InMemoryBus in that case. Real usage always provides a redis URL."""
        if url is None:
            raise ValueError("Bus requires a redis URL; use InMemoryBus for tests")
        self.url = url
        self._client = aioredis.from_url(url, decode_responses=True)

    async def publish(self, kind: str, payload: dict) -> str:
        raw = json.dumps(payload)
        if len(raw.encode()) > PAYLOAD_CAP_BYTES:
            raise ValueError(f"payload exceeds {PAYLOAD_CAP_BYTES} bytes")
        msg_id = await self._client.xadd(_stream_name(kind), {"payload": raw})
        return msg_id

    async def subscribe(
        self, kinds: list[str], block_ms: int = 1000
    ) -> AsyncIterator[BusEvent]:
        streams = {_stream_name(k): "$" for k in kinds}
        while True:
            res = await self._client.xread(streams, block=block_ms)
            if not res:
                continue
            for stream_name, entries in res:
                kind = stream_name.removeprefix("hypha:ev:")
                for entry_id, fields in entries:
                    streams[stream_name] = entry_id
                    try:
                        payload = json.loads(fields["payload"])
                    except (KeyError, json.JSONDecodeError):
                        continue
                    yield BusEvent(kind=kind, id=entry_id, payload=payload)

    async def aclose(self) -> None:
        await self._client.aclose()


class InMemoryBus:
    """Test-only Bus. Same interface, no Redis dependency.

    Keeps events in memory; subscribers see events published after they
    start iterating. Round-trip guarantees: publishers and subscribers share
    an asyncio.Queue per kind.
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[BusEvent]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, kind: str, payload: dict) -> str:
        raw = json.dumps(payload)
        if len(raw.encode()) > PAYLOAD_CAP_BYTES:
            raise ValueError(f"payload exceeds {PAYLOAD_CAP_BYTES} bytes")
        msg_id = uuid.uuid4().hex
        async with self._lock:
            queues = list(self._queues.get(kind, ()))
        ev = BusEvent(kind=kind, id=msg_id, payload=payload)
        for q in queues:
            await q.put(ev)
        return msg_id

    async def subscribe(
        self, kinds: list[str], block_ms: int = 1000
    ) -> AsyncIterator[BusEvent]:
        q: asyncio.Queue[BusEvent] = asyncio.Queue()
        async with self._lock:
            for k in kinds:
                self._queues.setdefault(k, []).append(q)
        try:
            while True:
                ev = await q.get()
                yield ev
        finally:
            async with self._lock:
                for k in kinds:
                    if q in self._queues.get(k, []):
                        self._queues[k].remove(q)
