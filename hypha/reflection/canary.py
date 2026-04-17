"""M6 — canary guard.

Role: the ONLY defense against prompt-evolution reward-hacking. A held-out
task set runs every candidate variant; any regression on canaries rejects
the variant regardless of main-metric gain. Non-negotiable.
Produces: canary pass/fail.
Consumes: candidate variant + canary task set.

Refuse to enable reflection (clustering + variant acceptance) until this is
real. Stubbing it is correct at scaffold time; enabling reflection against a
stubbed canary is a critical architectural violation.
"""

from __future__ import annotations


class CanaryGuard:
    async def evaluate(self, variant_id: str) -> bool:
        raise NotImplementedError(
            "M6: run canary task set against variant, compare pass rate to"
            " baseline; any regression returns False"
        )
