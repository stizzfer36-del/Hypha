"""M5 — human diff approval surface.

Role: take a `VerificationPassed` event + the associated worktree branch,
render the diff to a stream, capture accept / reject, append
`DecisionRecorded`, merge branch on accept.
Produces: `DecisionRecorded`.
Consumes: `VerificationPassed`, the worktree branch.

CLI implementation at M5; Telegram overlay later (shares event shape).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from hypha.events import Kind
from hypha.ledger import Ledger


@dataclass
class ApprovalDecision:
    accepted: bool
    rationale: str


def _git(repo_root: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *argv],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def render_diff(repo_root: Path, branch: str, base: str = "HEAD") -> str:
    res = _git(repo_root, "diff", f"{base}...{branch}")
    return res.stdout if res.returncode == 0 else res.stderr


class DiffApproval:
    def __init__(
        self,
        ledger: Ledger,
        repo_root: Path,
        ask: Callable[[str], bool],
    ):
        self.ledger = ledger
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.ask = ask  # UI: (diff_text) -> bool; injected so CLI/Telegram share

    async def request(
        self,
        verification_event_id: str,
        branch: str,
        base: str = "main",
    ) -> ApprovalDecision:
        diff_text = render_diff(self.repo_root, branch, base=base)
        accepted = bool(self.ask(diff_text))
        rationale = "human accept" if accepted else "human reject"

        if accepted:
            # Fast-forward merge only — refuse to create a merge commit here;
            # the branch was created off HEAD so ff is always possible unless
            # the base moved during the patch window. In that case, reject
            # and let the agent rebase+retry rather than silent merge.
            ff = _git(self.repo_root, "merge", "--ff-only", branch)
            if ff.returncode != 0:
                accepted = False
                rationale = f"ff-only merge failed: {ff.stderr.strip()}"

        await self.ledger.append(
            Kind.DECISION_RECORDED,
            "surface:cli",
            json.dumps(
                {
                    "branch": branch,
                    "accepted": accepted,
                    "rationale": rationale,
                }
            ),
            parent_id=verification_event_id,
        )
        return ApprovalDecision(accepted=accepted, rationale=rationale)
