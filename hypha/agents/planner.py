"""M6 — planner (split from fused).

Role: decompose an `IntentCreated` into sub-goals. Consume summaries, never
raw slices (that's the coder's input).
Produces: `PlanProposed`.
Consumes: `IntentCreated`, ledger summaries.
"""

from __future__ import annotations


class Planner:
    async def handle(self, intent_event_id: str) -> str:
        raise NotImplementedError("M6: decompose intent into sub-goals")
