"""M6 — archivist.

Role: record decisions, surface diffs to the human, detect missing-tool
patterns and emit `ToolProposed`.
Produces: `DecisionRecorded`, `ToolProposed`.
Consumes: `VerificationPassed` (surfaces a diff), failed-run clusters.
"""

from __future__ import annotations


class Archivist:
    async def record(self, verification_event_id: str) -> str:
        raise NotImplementedError(
            "M6: surface diff for human accept/reject, record decision"
        )

    async def scan_for_missing_tools(self) -> list[str]:
        raise NotImplementedError(
            "M6: look for agents repeatedly requesting info no tool surfaces,"
            " emit ToolProposed; human approves via the approval surface"
        )
