"""M6 — failure-signature clustering + nightly reflection.

Role: group failed runs by `failure_signature` and, for each cluster of
sufficient size, ask a long-context model to propose a prompt delta. Deltas
are emitted as `PromptVariantCandidate` events; they are not applied until
the canary guard passes.
Produces: `PromptVariantCandidate` (via ledger append).
Consumes: `RunLog` failed rows.
"""

from __future__ import annotations

import collections
import json
from dataclasses import dataclass
from typing import Awaitable, Callable

from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.reflection.run_log import Run, RunLog


ProposeFn = Callable[[str, list[Run]], Awaitable[str]]
# (prompt_id, failing_runs_in_cluster) -> proposed new prompt body


@dataclass
class Cluster:
    signature: str
    prompt_id: str
    size: int


class Clusterer:
    def __init__(
        self,
        run_log: RunLog,
        ledger: Ledger,
        propose: ProposeFn,
        min_cluster_size: int = 3,
    ):
        self.run_log = run_log
        self.ledger = ledger
        self.propose = propose
        self.min_cluster_size = min_cluster_size

    async def reflect_nightly(self, window: int = 500) -> list[Cluster]:
        failures = self.run_log.recent_failures(limit=window)
        buckets: dict[tuple[str, str], list[Run]] = collections.defaultdict(list)
        for r in failures:
            sig = r.failure_signature or "unknown"
            buckets[(r.prompt_id, sig)].append(r)

        clusters: list[Cluster] = []
        for (prompt_id, sig), rs in buckets.items():
            if len(rs) < self.min_cluster_size:
                continue
            clusters.append(Cluster(signature=sig, prompt_id=prompt_id, size=len(rs)))
            new_body = await self.propose(prompt_id, rs)
            await self.ledger.append(
                Kind.PROMPT_VARIANT_CANDIDATE,
                "reflection:clusterer",
                json.dumps(
                    {
                        "prompt_id": prompt_id,
                        "signature": sig,
                        "cluster_size": len(rs),
                        "body": new_body,
                    }
                ),
            )
        return clusters
