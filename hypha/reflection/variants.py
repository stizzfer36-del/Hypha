"""M6 — prompt variant store.

Role: integrity-checked registry of prompt templates and variants. A variant
is accepted only if canary passes and main-metric improves past a sequential
probability ratio threshold. Accepted variants are frozen for N days before
re-evolution.
Produces: `variants` rows.
Consumes: `PromptVariantCandidate` events.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Variant:
    id: str
    prompt_id: str
    body_hash: str
    created_ts: float
    frozen_until_ts: float
    accepted: bool


class VariantStore:
    async def register(self, prompt_id: str, body: str) -> Variant:
        raise NotImplementedError("M6: hash body, persist with frozen_until_ts")

    async def accept(self, variant_id: str) -> None:
        raise NotImplementedError("M6: mark accepted, set freeze window")
