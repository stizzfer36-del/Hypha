"""M6 — coder (split from fused).

Role: receive a `PlanProposed` + context slices, apply a patch on a worktree.
Produces: `PatchSubmitted`.
Consumes: `PlanProposed`, joint-query slices, router responses.
"""

from __future__ import annotations


class Coder:
    async def handle(self, plan_event_id: str) -> str:
        raise NotImplementedError("M6: apply patch on worktree, publish PatchSubmitted")
