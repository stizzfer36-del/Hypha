"""M5 — human diff approval surface.

Role: take a `VerificationPassed` + patch, present the diff to the human,
wait for accept / reject, write `DecisionRecorded`, merge on accept.
Produces: `DecisionRecorded`.
Consumes: `VerificationPassed`, the worktree branch.

CLI implementation at M5; Telegram overlay later (share the decision event
shape so both surfaces are interchangeable).
"""

from __future__ import annotations


class DiffApproval:
    async def request(self, verification_event_id: str) -> str:
        raise NotImplementedError(
            "M5: render diff, capture accept/reject, append DecisionRecorded,"
            " merge branch on accept"
        )
