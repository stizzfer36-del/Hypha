"""M6 — planner (split from fused).

Role: decompose an `IntentCreated` into sub-goals. Consume summaries, never
raw slices (that's the coder's input).
Produces: `PlanProposed` with a list of sub-goal strings.
Consumes: `IntentCreated`, ledger summaries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.router import Request, Router


PROMPT = """You are Hypha's planner. Decompose the intent into 1-5 sub-goals,
ordered so earlier steps unlock later ones. Respond with ONLY a JSON object:

{{"subgoals": ["step one", "step two", ...]}}

Intent:
{intent}

Summary of recent repo activity (may be empty):
{summary}
"""


class PlannerError(ValueError):
    pass


@dataclass
class Plan:
    event_id: str
    subgoals: list[str]


def _parse_plan(text: str) -> list[str]:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise PlannerError(f"planner response not JSON: {e}") from e
    if not isinstance(obj, dict) or "subgoals" not in obj:
        raise PlannerError('planner response missing "subgoals"')
    subgoals = obj["subgoals"]
    if not isinstance(subgoals, list) or not all(isinstance(s, str) for s in subgoals):
        raise PlannerError("subgoals must be a list of strings")
    if not 1 <= len(subgoals) <= 10:
        raise PlannerError(f"subgoals must have 1..10 entries; got {len(subgoals)}")
    return [s.strip() for s in subgoals if s.strip()]


class Planner:
    def __init__(self, ledger: Ledger, router: Router):
        self.ledger = ledger
        self.router = router

    async def _intent_text(self, event_id: str) -> str:
        rows = await self.ledger.recent(kind=Kind.INTENT_CREATED, limit=200)
        for r in rows:
            if r.id == event_id:
                try:
                    return json.loads(r.payload).get("text", "")
                except json.JSONDecodeError:
                    return r.payload
        raise KeyError(f"intent {event_id} not found")

    async def _summary(self) -> str:
        rows = await self.ledger.recent(limit=10)
        lines = [f"- {r.kind}: {r.actor}" for r in rows]
        return "\n".join(lines) if lines else "(none)"

    async def handle(self, intent_event_id: str) -> Plan:
        intent = await self._intent_text(intent_event_id)
        summary = await self._summary()
        resp = await self.router.call(
            Request(
                prompt=PROMPT.format(intent=intent, summary=summary),
                max_tokens=512,
                capability="plan",
            )
        )
        subgoals = _parse_plan(resp.text)
        eid = await self.ledger.append(
            Kind.PLAN_PROPOSED,
            "agent:planner",
            json.dumps(
                {
                    "intent": intent,
                    "subgoals": subgoals,
                    "provider": resp.provider,
                    "model": resp.model,
                }
            ),
            parent_id=intent_event_id,
        )
        return Plan(event_id=eid, subgoals=subgoals)
