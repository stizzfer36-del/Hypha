"""M4 — router + bus tests.

Router:
  * fallback on RateLimited
  * fallback on TransientError
  * abort on PermanentError
  * respects per-provider budget

Bus:
  * InMemoryBus publish/subscribe round-trip
  * payload cap enforced at publish
  * (fakeredis) real Bus subscribe yields after publish
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import pytest

from hypha.bus import InMemoryBus, Bus, PAYLOAD_CAP_BYTES
from hypha.router import (
    OpenAICompatibleProvider,
    PermanentError,
    RateLimited,
    Request,
    Response,
    Router,
    TransientError,
)


# ---- Router ------------------------------------------------------------------


@dataclass
class DummyProvider:
    name: str
    plan: list[str | Exception] = field(default_factory=list)
    cost_v: float = 0.0
    latency_v: int = 100

    def supports(self, capability: str) -> bool:
        return True

    def cost(self, capability: str) -> float:
        return self.cost_v

    def latency_ms(self, capability: str) -> int:
        return self.latency_v

    async def call(self, req: Request) -> Response:
        item = self.plan.pop(0)
        if isinstance(item, Exception):
            raise item
        return Response(
            text=item, provider=self.name, model="m", tokens_in=0, tokens_out=1, ms=0
        )


async def test_router_falls_back_on_rate_limit() -> None:
    p1 = DummyProvider(name="a", plan=[RateLimited("a")], cost_v=0.0, latency_v=100)
    p2 = DummyProvider(name="b", plan=["hello"], cost_v=0.1, latency_v=500)
    r = Router([p1, p2])
    resp = await r.call(Request(prompt="x"))
    assert resp.provider == "b"
    assert ("a", "RateLimited") in r._last_errors


async def test_router_falls_back_on_transient() -> None:
    p1 = DummyProvider(name="a", plan=[TransientError("a 503")])
    p2 = DummyProvider(name="b", plan=["ok"], cost_v=0.1)
    r = Router([p1, p2])
    resp = await r.call(Request(prompt="x"))
    assert resp.provider == "b"


async def test_router_aborts_on_permanent_error() -> None:
    p1 = DummyProvider(name="a", plan=[PermanentError("a 400")])
    p2 = DummyProvider(name="b", plan=["ok"])
    r = Router([p1, p2])
    with pytest.raises(PermanentError):
        await r.call(Request(prompt="x"))


async def test_router_skips_exhausted_budget() -> None:
    p1 = DummyProvider(name="a", plan=["reply"], cost_v=0.0)
    p2 = DummyProvider(name="b", plan=["fallback"], cost_v=0.1)
    r = Router([p1, p2])
    r.budgets["a"].tokens_cap = 1  # will not fit max_tokens=2048
    resp = await r.call(Request(prompt="x"))
    assert resp.provider == "b"


async def test_router_no_eligible_providers() -> None:
    r = Router([])
    with pytest.raises(RuntimeError):
        await r.call(Request(prompt="x"))


async def test_openai_compatible_provider_maps_429() -> None:
    async def fake_http(url, headers, body, timeout):
        return 429, {}

    p = OpenAICompatibleProvider(
        name="groq",
        api_key="k",
        base_url="https://example",
        model="m",
        http_post=fake_http,
    )
    with pytest.raises(RateLimited):
        await p.call(Request(prompt="x"))


async def test_openai_compatible_provider_happy_path() -> None:
    async def fake_http(url, headers, body, timeout):
        assert headers["Authorization"] == "Bearer k"
        return 200, {
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }

    p = OpenAICompatibleProvider(
        name="groq",
        api_key="k",
        base_url="https://example",
        model="m",
        http_post=fake_http,
    )
    resp = await p.call(Request(prompt="hello"))
    assert resp.text == "hi"
    assert resp.tokens_in == 5 and resp.tokens_out == 2


# ---- Bus ---------------------------------------------------------------------


async def test_inmemory_bus_roundtrip() -> None:
    bus = InMemoryBus()

    async def consumer(seen: list[str]) -> None:
        async for ev in bus.subscribe(["IntentCreated"]):
            seen.append(ev.payload["text"])
            if len(seen) >= 2:
                return

    seen: list[str] = []
    task = asyncio.create_task(consumer(seen))
    await asyncio.sleep(0)  # let the consumer register
    await bus.publish("IntentCreated", {"text": "a"})
    await bus.publish("IntentCreated", {"text": "b"})
    await asyncio.wait_for(task, timeout=2.0)
    assert seen == ["a", "b"]


async def test_inmemory_bus_enforces_cap() -> None:
    bus = InMemoryBus()
    big = "x" * (PAYLOAD_CAP_BYTES + 10)
    with pytest.raises(ValueError):
        await bus.publish("X", {"blob": big})


async def test_fakeredis_bus_roundtrip() -> None:
    fakeredis = pytest.importorskip("fakeredis")
    from fakeredis.aioredis import FakeRedis

    bus = Bus.__new__(Bus)
    bus.url = "redis://fake"
    bus._client = FakeRedis(decode_responses=True)

    async def consumer(seen: list[str]) -> None:
        async for ev in bus.subscribe(["IntentCreated"], block_ms=100):
            seen.append(ev.payload["text"])
            if len(seen) >= 1:
                return

    seen: list[str] = []
    task = asyncio.create_task(consumer(seen))
    await asyncio.sleep(0.1)
    await bus.publish("IntentCreated", {"text": "hello"})
    await asyncio.wait_for(task, timeout=3.0)
    assert seen == ["hello"]
    await bus.aclose()
