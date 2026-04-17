"""M4 — capability-cost-latency model router.

Role: route each LLM call to the cheapest provider that clears the task's
capability bar, with backpressure and fallback. Never logs API keys. Never
routes to a provider whose key is unset.
Produces: model responses.
Consumes: per-provider API keys (via `config.load`).

Fallback chain (spec): Groq → Gemini → DeepSeek → OpenRouter free tier.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Request:
    prompt: str
    max_tokens: int
    capability: str  # "plan" | "code" | "verify" | "reflect"


@dataclass
class Response:
    text: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    ms: int


class Router:
    async def call(self, req: Request) -> Response:
        raise NotImplementedError(
            "M4: score providers by (capability, cost, latency), try in order,"
            " honor per-provider budgets and rate limits, fall back on 429/5xx"
        )
