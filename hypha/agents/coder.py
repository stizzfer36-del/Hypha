"""M6 — coder (split from fused).

Role: receive a `PlanProposed` + context slices, apply a patch on a worktree.
Produces: `PatchSubmitted`.
Consumes: `PlanProposed`, joint-query slices, router responses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from hypha.agents._patch import PatchFormatError, apply_patch, parse_patch
from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.router import Request, Router
from hypha.sandbox.worktree import Worktree, WorktreeHandle


PROMPT = """You are Hypha's coder. Produce ONLY a JSON object, no prose.

Shape:
{{"files": {{"relative/path.py": "full file contents", ...}}}}

Write complete file contents; we overwrite or create. Include only files you
are changing.

Plan sub-goals:
{subgoals}

Context (ranked slices; may be empty):
{context}
"""


@dataclass
class Submission:
    event_id: str
    branch: str
    worktree: Path
    files: list[str]


class Coder:
    def __init__(
        self,
        ledger: Ledger,
        router: Router,
        repo_root: Path,
        context_render: Optional[Callable[[str], str]] = None,
    ):
        self.ledger = ledger
        self.router = router
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.context_render = context_render

    async def _plan_subgoals(self, plan_event_id: str) -> list[str]:
        rows = await self.ledger.recent(kind=Kind.PLAN_PROPOSED, limit=50)
        for r in rows:
            if r.id == plan_event_id:
                try:
                    return list(json.loads(r.payload).get("subgoals", []))
                except json.JSONDecodeError:
                    return []
        raise KeyError(f"plan {plan_event_id} not found")

    async def handle(self, plan_event_id: str) -> Submission:
        subgoals = await self._plan_subgoals(plan_event_id)
        ctx = ""
        if self.context_render is not None:
            try:
                ctx = self.context_render("\n".join(subgoals)) or ""
            except Exception as e:
                ctx = f"(context render failed: {e})"

        resp = await self.router.call(
            Request(
                prompt=PROMPT.format(
                    subgoals="\n".join(f"- {s}" for s in subgoals),
                    context=ctx,
                ),
                max_tokens=2048,
                capability="code",
            )
        )

        wtm = Worktree(self.repo_root)
        handle: WorktreeHandle = wtm.create()
        try:
            files = parse_patch(resp.text)
            written = apply_patch(handle.path, files)
        except PatchFormatError as e:
            # Emit a failed submission so the verifier can see it.
            eid = await self.ledger.append(
                Kind.PATCH_SUBMITTED,
                "agent:coder",
                json.dumps(
                    {
                        "branch": handle.branch,
                        "files": [],
                        "error": str(e),
                        "provider": resp.provider,
                        "model": resp.model,
                    }
                ),
                parent_id=plan_event_id,
            )
            return Submission(
                event_id=eid, branch=handle.branch, worktree=handle.path, files=[]
            )

        eid = await self.ledger.append(
            Kind.PATCH_SUBMITTED,
            "agent:coder",
            json.dumps(
                {
                    "branch": handle.branch,
                    "files": written,
                    "provider": resp.provider,
                    "model": resp.model,
                }
            ),
            parent_id=plan_event_id,
        )
        return Submission(
            event_id=eid, branch=handle.branch, worktree=handle.path, files=written
        )
