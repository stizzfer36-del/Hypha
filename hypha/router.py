"""M4 — capability-cost-latency model router.

Role: route each LLM call to the cheapest provider that clears the task's
capability bar, with backpressure and fallback. Never logs API keys. Never
routes to a provider whose key is unset.
Produces: model responses.
Consumes: per-provider API keys (via `config.load`).

Fallback chain (spec): Groq -> Gemini -> DeepSeek -> OpenRouter.

Design notes for M4:
  * Provider list is injected — tests pass fakes; production code instantiates
    `default_providers(config)` which returns only those whose key is set.
  * Each provider exposes (capability -> cost, latency) hints; `Router` sorts
    its candidate pool by (cost, latency).
  * On `RateLimited` or transient (5xx) errors we fall through to the next
    provider. Permanent errors (4xx non-429) abort.
  * A per-provider `budget` caps tokens-out per process lifetime; exceeded
    providers are skipped even if keys are set.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol

import httpx


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


class RateLimited(Exception):
    pass


class TransientError(Exception):
    pass


class PermanentError(Exception):
    pass


class Provider(Protocol):
    name: str

    def supports(self, capability: str) -> bool: ...
    def cost(self, capability: str) -> float: ...
    def latency_ms(self, capability: str) -> int: ...
    async def call(self, req: Request) -> Response: ...


@dataclass
class ProviderBudget:
    tokens_cap: int = 1_000_000
    tokens_used: int = 0

    def has_room(self, ask: int) -> bool:
        return self.tokens_used + ask <= self.tokens_cap

    def charge(self, n: int) -> None:
        self.tokens_used += n


class Router:
    def __init__(self, providers: list[Provider]):
        self.providers = list(providers)
        self.budgets: dict[str, ProviderBudget] = {
            p.name: ProviderBudget() for p in providers
        }
        self._last_errors: list[tuple[str, str]] = []

    def _candidates(self, req: Request) -> list[Provider]:
        eligible = [
            p
            for p in self.providers
            if p.supports(req.capability)
            and self.budgets[p.name].has_room(req.max_tokens)
        ]
        eligible.sort(key=lambda p: (p.cost(req.capability), p.latency_ms(req.capability)))
        return eligible

    async def call(self, req: Request) -> Response:
        self._last_errors = []
        last: Exception | None = None
        for p in self._candidates(req):
            try:
                t0 = time.perf_counter()
                resp = await p.call(req)
                resp.ms = int((time.perf_counter() - t0) * 1000)
                self.budgets[p.name].charge(resp.tokens_out)
                return resp
            except (RateLimited, TransientError) as e:
                self._last_errors.append((p.name, type(e).__name__))
                last = e
                continue
            except PermanentError as e:
                self._last_errors.append((p.name, type(e).__name__))
                raise
        raise RuntimeError(
            f"no provider succeeded; attempts={self._last_errors}"
            if self._last_errors
            else "no eligible providers"
        ) from last


# ---- Concrete providers ------------------------------------------------------

HTTPRequester = Callable[[str, dict, dict, float], Awaitable[tuple[int, dict]]]


async def _http_post(
    url: str, headers: dict, body: dict, timeout: float
) -> tuple[int, dict]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=headers, json=body)
    try:
        return r.status_code, r.json()
    except json.JSONDecodeError:
        return r.status_code, {"raw": r.text}


@dataclass
class OpenAICompatibleProvider:
    """Covers Groq, DeepSeek, OpenRouter — all use the OpenAI chat-completions
    shape. Gemini has its own shape; see GeminiProvider below."""

    name: str
    api_key: str
    base_url: str
    model: str
    capabilities: tuple[str, ...] = ("plan", "code", "verify", "reflect")
    cost_per_1k: float = 0.001  # USD; 0 on free tiers
    expected_latency_ms: int = 1500
    http_post: HTTPRequester = field(default=_http_post)

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def cost(self, capability: str) -> float:
        return self.cost_per_1k

    def latency_ms(self, capability: str) -> int:
        return self.expected_latency_ms

    async def call(self, req: Request) -> Response:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": req.prompt}],
            "max_tokens": req.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        status, data = await self.http_post(url, headers, body, 60.0)
        if status == 429:
            raise RateLimited(self.name)
        if 500 <= status < 600:
            raise TransientError(f"{self.name} {status}")
        if status >= 400:
            raise PermanentError(f"{self.name} {status}: {data}")
        try:
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return Response(
                text=text,
                provider=self.name,
                model=self.model,
                tokens_in=int(usage.get("prompt_tokens", 0)),
                tokens_out=int(usage.get("completion_tokens", 0)),
                ms=0,  # filled in by router
            )
        except (KeyError, IndexError, TypeError) as e:
            raise PermanentError(f"{self.name} malformed response: {e}") from e


def default_providers(cfg) -> list[Provider]:
    """Build the standard fallback chain from loaded config.
    Providers with unset keys are silently omitted."""
    out: list[Provider] = []
    if cfg.groq_api_key:
        out.append(
            OpenAICompatibleProvider(
                name="groq",
                api_key=cfg.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
                model="llama-3.3-70b-versatile",
                cost_per_1k=0.0,
                expected_latency_ms=400,
            )
        )
    if cfg.deepseek_api_key:
        out.append(
            OpenAICompatibleProvider(
                name="deepseek",
                api_key=cfg.deepseek_api_key,
                base_url="https://api.deepseek.com/v1",
                model="deepseek-chat",
                cost_per_1k=0.0,
                expected_latency_ms=1500,
            )
        )
    if cfg.openrouter_api_key:
        out.append(
            OpenAICompatibleProvider(
                name="openrouter",
                api_key=cfg.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
                model="meta-llama/llama-3.3-70b-instruct:free",
                cost_per_1k=0.0,
                expected_latency_ms=2500,
            )
        )
    # Gemini has its own wire format; omitted at M4 — OpenAI-compatible
    # chain covers the zero-budget path. Add GeminiProvider in a follow-up
    # once M6 reflection actually needs long-context routing.
    return out
