"""M3 — fused planner+coder+verifier (single agent).

Role: day-one agent. Takes an `IntentCreated`, produces a `PlanProposed`,
applies a patch on a worktree, runs verification, emits `PatchSubmitted` +
`VerificationPassed|Failed`. Split into dedicated roles at M6.
Produces: plan events, patch events, verification events.
Consumes: `IntentCreated`, context-engine slices, router responses.
"""

from __future__ import annotations


class FusedAgent:
    async def handle(self, intent_event_id: str) -> str:
        raise NotImplementedError(
            "M3: plan -> context slice -> code -> verify -> publish events."
            " Retry with failure context up to a budget on verification fail."
        )
