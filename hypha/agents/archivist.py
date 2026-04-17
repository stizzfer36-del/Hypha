"""M6 — archivist.

Role: record decisions, surface diffs to the human, detect missing-tool
patterns and emit `ToolProposed`.
Produces: `DecisionRecorded`, `ToolProposed`.
Consumes: `VerificationPassed`, failed-run clusters.
"""

from __future__ import annotations

import collections
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.reflection.run_log import RunLog
from hypha.surface.diff_approval import DiffApproval


@dataclass
class ArchiveResult:
    decision_event_id: str
    accepted: bool
    rationale: str


class Archivist:
    """Bridges verifier output to the approval surface and the reflection
    layer. The ask() callable lets the CLI or Telegram decide accept/reject."""

    def __init__(
        self,
        ledger: Ledger,
        repo_root: Path,
        ask: Callable[[str], bool],
        run_log: RunLog | None = None,
        min_tool_cluster: int = 3,
    ):
        self.ledger = ledger
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.ask = ask
        self.run_log = run_log
        self.min_tool_cluster = min_tool_cluster
        self._approval = DiffApproval(ledger, repo_root, ask)

    async def _verification(self, event_id: str) -> dict:
        rows = await self.ledger.recent(kind=Kind.VERIFICATION_PASSED, limit=100)
        for r in rows:
            if r.id == event_id:
                try:
                    return json.loads(r.payload)
                except json.JSONDecodeError:
                    return {}
        raise KeyError(f"verification {event_id} not found")

    async def record(
        self, verification_event_id: str, base: str = "main"
    ) -> ArchiveResult:
        summary = await self._verification(verification_event_id)
        branch = summary.get("branch")
        if not branch:
            raise ValueError("verification payload missing branch")
        decision = await self._approval.request(
            verification_event_id, branch=branch, base=base
        )
        # DiffApproval already wrote DecisionRecorded; fetch its id for
        # the return value.
        rows = await self.ledger.recent(kind=Kind.DECISION_RECORDED, limit=1)
        return ArchiveResult(
            decision_event_id=rows[0].id if rows else "",
            accepted=decision.accepted,
            rationale=decision.rationale,
        )

    _TOOL_REGEX = re.compile(
        r"(?i)(?:need|missing|no tool for|would need|wish I could)\s+([a-z0-9_\-\s]{3,40})"
    )

    async def scan_for_missing_tools(self) -> list[str]:
        """Cluster failed-run stdout for repeated "need X" phrases. Emits a
        `ToolProposed` event per cluster crossing the threshold. The human
        approves the tool creation via whichever surface is wired up; this
        function only *proposes*."""
        if self.run_log is None:
            return []
        failures = self.run_log.recent_failures(limit=500)
        buckets: dict[str, int] = collections.Counter()
        for run in failures:
            # We only have the signature on the Run row; a real
            # instrumentation layer would pass through the stdout tail.
            # Here we treat failure_signature as the proxy.
            sig = run.failure_signature or ""
            m = self._TOOL_REGEX.search(sig)
            if m:
                buckets[m.group(1).strip().lower()] += 1
        proposed: list[str] = []
        for tool, n in buckets.items():
            if n >= self.min_tool_cluster:
                await self.ledger.append(
                    Kind.TOOL_PROPOSED,
                    "agent:archivist",
                    json.dumps({"tool": tool, "cluster_size": n}),
                )
                proposed.append(tool)
        return proposed
