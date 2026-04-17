#!/usr/bin/env bash
# M4 end-to-end verify — model router + event bus.
# Kill-gate: p50 intent latency > 10 min under normal rate limits -> STOP.
# We can't measure real-provider latency here without credentials, so this
# script exercises (a) the fallback chain when provider 1 is forced to 429,
# and (b) in-memory bus publish/subscribe round-trip; the real-latency
# gate must be walked manually after credentials are added.
#   PY=.venv/bin/python bash scripts/verify_m4.sh
set -euo pipefail
PY=${PY:-python}

echo "== unit tests =="
$PY -m pytest -q tests/test_router.py

echo "== end-to-end: forced-429 triggers fallback chain =="
$PY - <<'PYEOF'
import asyncio, time
from dataclasses import dataclass, field

from hypha.router import (
    Router, Request, Response, RateLimited, OpenAICompatibleProvider,
)

@dataclass
class CountingHTTP:
    n: int = 0

    async def __call__(self, url, headers, body, timeout):
        self.n += 1
        if self.n == 1:
            return 429, {}
        return 200, {
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }

http = CountingHTTP()
p1 = OpenAICompatibleProvider(
    name="groq", api_key="k1", base_url="https://a", model="m1",
    cost_per_1k=0.0, expected_latency_ms=400, http_post=http,
)
p2 = OpenAICompatibleProvider(
    name="deepseek", api_key="k2", base_url="https://b", model="m2",
    cost_per_1k=0.0, expected_latency_ms=1500, http_post=http,
)
r = Router([p1, p2])

t0 = time.perf_counter()
resp = asyncio.run(r.call(Request(prompt="hello", max_tokens=32)))
ms = int((time.perf_counter() - t0) * 1000)

assert resp.provider == "deepseek", f"expected deepseek fallback, got {resp.provider}"
assert ("groq", "RateLimited") in r._last_errors
print(f"fallback OK; provider={resp.provider}; attempts={r._last_errors}; ms={ms}")
assert ms < 10 * 60 * 1000, "kill-gate breached on mocked path"
PYEOF

echo "== end-to-end: bus publish/subscribe round-trip =="
$PY - <<'PYEOF'
import asyncio

from hypha.bus import InMemoryBus

async def main():
    bus = InMemoryBus()
    seen = []
    async def consumer():
        async for ev in bus.subscribe(["PatchSubmitted"]):
            seen.append(ev.payload["id"])
            if len(seen) == 3:
                return
    t = asyncio.create_task(consumer())
    await asyncio.sleep(0)
    for i in range(3):
        await bus.publish("PatchSubmitted", {"id": i})
    await asyncio.wait_for(t, timeout=2.0)
    assert seen == [0, 1, 2], seen
    print("bus OK")

asyncio.run(main())
PYEOF

echo "== security self-check =="
# No api_key logged or echoed from router (no print of self.api_key or fields)
if grep -E 'print\([^)]*api_key' hypha/router.py ; then
  echo "FAIL: api_key printed"; exit 1
fi
# Payload cap exists and is used
grep -q "PAYLOAD_CAP_BYTES" hypha/bus.py
# Redis client from_url is the only construction path (auth in the URL)
grep -q "aioredis.from_url" hypha/bus.py
echo "security OK"

echo "verify_m4 PASS"
echo
echo "NOTE: the p50 latency kill-gate (> 10 min) must be re-checked after"
echo "real provider credentials are added. Mocked path is ~0 ms."
