"""M3/M5 — behavioral diff via replayed property tests.

Role: guard against "tests pass but intent violated". Replays recorded
traces and property tests against both the pre-patch and post-patch
binaries; flags divergence as potential semantic drift.
Produces: diff payload (which properties diverged).
Consumes: a worktree path + captured traces from the runtime-trace layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DiffResult:
    divergent: bool
    properties: list[str]  # which properties changed output


class BehavioralDiff:
    async def run(self, pre: Path, post: Path) -> DiffResult:
        raise NotImplementedError(
            "M3 stub / M5 real: replay property tests, compare outputs,"
            " flag divergence"
        )
