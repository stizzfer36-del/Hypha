"""M7 — task claim with optimistic lock.

Role: claim-before-act over the ledger. If two devices claim the same task,
one wins and the other sees conflict and backs off. Conflict never results
in silent merge; it raises to the human.
Produces: `TaskClaimed`, `TaskReleased`.
Consumes: tasks from the event bus.
"""

from __future__ import annotations


class Claim:
    async def try_claim(self, task_id: str, device_id: str) -> bool:
        raise NotImplementedError(
            "M7: conditional INSERT into claims table; returns False on conflict"
        )

    async def release(self, task_id: str, device_id: str) -> None:
        raise NotImplementedError("M7: delete claim row; publish TaskReleased")
