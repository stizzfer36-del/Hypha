"""M6 — verifier (split from fused).

Role: run tests, type-check, behavioral diff. Publish pass/fail with
diagnostics so the coder can retry with failure context.
Produces: `VerificationPassed` | `VerificationFailed`.
Consumes: `PatchSubmitted`.
"""

from __future__ import annotations


class Verifier:
    async def handle(self, patch_event_id: str) -> str:
        raise NotImplementedError("M6: run pytest, mypy, behavioral diff; publish result")
