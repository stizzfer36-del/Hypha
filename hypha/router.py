"""M3 scaffold / M4 implementation — capability-cost-latency model router.

Role: route each LLM call to the cheapest provider that clears the task's
capability bar, with backpressure and fallback. Never logs API keys. Never
routes to a provider whose key is unset.
Produces: model responses.
Consumes: per-provider API keys (via `config.load`).

Fallback chain (spec): Groq -> Gemini -> DeepSeek -> OpenRouter.

At M3 the abstract `Router` protocol is what the fused agent calls; any
concrete implementation (real providers at M4, fakes in tests) satisfies it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Request:
    prompt: str
    max_tokens: int = 2048
    capability: str = "code"  # "plan" | "code" | "verify" | "reflect"


@dataclass
class Response:
    text: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    ms: int


class Router(Protocol):
    async def call(self, req: Request) -> Response: ...


class LiveRouter:
    """M4 — real provider router. Stub until M4."""

    async def call(self, req: Request) -> Response:
        raise NotImplementedError(
            "M4: score providers by (capability, cost, latency), try in order,"
            " honor per-provider budgets and rate limits, fall back on 429/5xx"
        )
