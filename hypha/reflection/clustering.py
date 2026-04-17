"""M6 — failure-signature clustering.

Role: nightly job (Gemini long-context) clusters failed runs into signatures
and proposes prompt deltas as `PromptVariantCandidate` events.
Produces: `PromptVariantCandidate`.
Consumes: `RunLog` failed rows.
"""

from __future__ import annotations


class Clusterer:
    async def reflect_nightly(self) -> list[str]:
        raise NotImplementedError(
            "M6: pull failed runs since last reflection, cluster, propose"
            " variants via long-context model"
        )
