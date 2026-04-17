"""M6 — verifier (split from fused).

Role: run tests, type-check, behavioral diff. Publish pass/fail with
diagnostics so the coder can retry with failure context.
Produces: `VerificationPassed` | `VerificationFailed`.
Consumes: `PatchSubmitted`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.verify.behavioral_diff import BehavioralDiff
from hypha.verify.pytest_runner import PytestRunner
from hypha.verify.typecheck import TypeChecker


@dataclass
class VerifyResult:
    event_id: str
    passed: bool
    rc: int
    mypy_ok: bool
    divergent: bool
    summary: dict


class Verifier:
    def __init__(
        self,
        ledger: Ledger,
        pytest_runner: Optional[PytestRunner] = None,
        type_checker: Optional[TypeChecker] = None,
        behavioral: Optional[BehavioralDiff] = None,
    ):
        self.ledger = ledger
        self.pytest_runner = pytest_runner or PytestRunner()
        self.type_checker = type_checker or TypeChecker()
        self.behavioral = behavioral or BehavioralDiff()

    async def _submission(self, patch_event_id: str) -> dict:
        rows = await self.ledger.recent(kind=Kind.PATCH_SUBMITTED, limit=50)
        for r in rows:
            if r.id == patch_event_id:
                try:
                    return json.loads(r.payload)
                except json.JSONDecodeError:
                    return {}
        raise KeyError(f"patch {patch_event_id} not found")

    async def handle(
        self, patch_event_id: str, worktree: Path, pre: Optional[Path] = None
    ) -> VerifyResult:
        sub = await self._submission(patch_event_id)
        if sub.get("error"):
            # Coder already errored out; propagate as VerificationFailed.
            eid = await self.ledger.append(
                Kind.VERIFICATION_FAILED,
                "agent:verifier",
                json.dumps({"reason": "coder-error", "detail": sub.get("error")}),
                parent_id=patch_event_id,
            )
            return VerifyResult(
                event_id=eid,
                passed=False,
                rc=-1,
                mypy_ok=False,
                divergent=True,
                summary={"reason": "coder-error"},
            )

        worktree = Path(worktree).resolve()
        pytest_result = await self.pytest_runner.run(worktree)
        mypy_result = await self.type_checker.run(worktree)

        divergent = False
        behavioral_detail: dict = {}
        if pre is not None:
            diff = await self.behavioral.run(pre, worktree)
            divergent = diff.divergent
            behavioral_detail = {
                "properties": diff.properties,
                "divergent": diff.divergent,
            }

        passed = (
            pytest_result.passed
            and (mypy_result.passed or not mypy_result.configured)
            and not divergent
        )
        summary = {
            "branch": sub.get("branch"),
            "rc": pytest_result.rc,
            "pytest_ms": pytest_result.ms,
            "mypy_configured": mypy_result.configured,
            "mypy_ok": mypy_result.passed,
            "mypy_errors": mypy_result.errors[:20],
            "behavioral": behavioral_detail,
            "stdout_tail": pytest_result.stdout_tail,
        }

        kind = Kind.VERIFICATION_PASSED if passed else Kind.VERIFICATION_FAILED
        eid = await self.ledger.append(
            kind, "agent:verifier", json.dumps(summary), parent_id=patch_event_id
        )
        return VerifyResult(
            event_id=eid,
            passed=passed,
            rc=pytest_result.rc,
            mypy_ok=mypy_result.passed,
            divergent=divergent,
            summary=summary,
        )
