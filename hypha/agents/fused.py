"""M3 — fused planner+coder+verifier (single agent).

Role: day-one agent. Takes an `IntentCreated`, produces a `PlanProposed`,
applies a patch on a worktree, runs verification, emits `PatchSubmitted` +
`VerificationPassed|Failed`. Split into dedicated roles at M6.
Produces: plan events, patch events, verification events.
Consumes: `IntentCreated`, optional context-engine slices, router responses.

Patch shape: the router response is a JSON object
  {"files": {"relative/path.py": "full file contents", ...}}
so we never parse unified diffs — simpler, less room for escape
vulnerabilities, and straightforward to audit in the ledger.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.router import Request, Router
from hypha.sandbox.worktree import Worktree, WorktreeHandle
from hypha.verify.pytest_runner import PytestRunner


PROMPT_TEMPLATE = """You are Hypha's coder. Produce ONLY a JSON object, no prose.

Shape:
{{"files": {{"relative/path.py": "full file contents", ...}}}}

The paths must be relative to the repo root. Write complete file contents;
we overwrite or create. Do not include any files you are not changing.

Intent:
{intent}

Context (ranked slices; may be empty):
{context}
"""


@dataclass
class LoopResult:
    ok: bool
    branch: str
    worktree: Path
    verification_event_id: str


class PatchFormatError(ValueError):
    pass


def _parse_patch(text: str) -> dict[str, str]:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise PatchFormatError(f"response is not valid JSON: {e}") from e
    if not isinstance(obj, dict) or "files" not in obj or not isinstance(obj["files"], dict):
        raise PatchFormatError('response must be {"files": {...}}')
    files = obj["files"]
    for k, v in files.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise PatchFormatError("each file entry must be str->str")
        # No path traversal or absolute paths.
        if k.startswith("/") or ".." in Path(k).parts:
            raise PatchFormatError(f"unsafe path: {k}")
    return files


def _apply_patch(root: Path, files: dict[str, str]) -> list[str]:
    written: list[str] = []
    for rel, body in files.items():
        dest = (root / rel).resolve()
        # Belt & braces: confirm dest stays under root after resolution.
        if not str(dest).startswith(str(root.resolve()) + "/") and dest != root.resolve():
            raise PatchFormatError(f"patch escapes worktree: {rel}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body)
        written.append(rel)
    return written


class FusedAgent:
    def __init__(
        self,
        ledger: Ledger,
        router: Router,
        repo_root: Path,
        runner: Optional[PytestRunner] = None,
        context_render: Optional[callable] = None,  # type: ignore[type-arg]
    ):
        self.ledger = ledger
        self.router = router
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.runner = runner or PytestRunner()
        self.context_render = context_render

    async def _intent_text(self, event_id: str) -> str:
        # Ledger doesn't expose single-event fetch; scan recent.
        rows = await self.ledger.recent(kind=Kind.INTENT_CREATED, limit=200)
        for r in rows:
            if r.id == event_id:
                try:
                    return json.loads(r.payload).get("text", "")
                except json.JSONDecodeError:
                    return r.payload
        raise KeyError(f"intent {event_id} not found in ledger")

    async def handle(self, intent_event_id: str) -> LoopResult:
        intent_text = await self._intent_text(intent_event_id)

        await self.ledger.append(
            Kind.PLAN_PROPOSED,
            "agent:fused",
            json.dumps({"intent": intent_text}),
            parent_id=intent_event_id,
        )

        context_str = ""
        if self.context_render is not None:
            try:
                context_str = self.context_render(intent_text) or ""
            except Exception as e:
                context_str = f"(context render failed: {e})"

        prompt = PROMPT_TEMPLATE.format(intent=intent_text, context=context_str)
        resp = await self.router.call(
            Request(prompt=prompt, max_tokens=2048, capability="code")
        )

        worktree_mgr = Worktree(self.repo_root)
        handle: WorktreeHandle = worktree_mgr.create()

        try:
            files = _parse_patch(resp.text)
            written = _apply_patch(handle.path, files)
            patch_id = await self.ledger.append(
                Kind.PATCH_SUBMITTED,
                "agent:fused",
                json.dumps(
                    {
                        "branch": handle.branch,
                        "files": written,
                        "provider": resp.provider,
                        "model": resp.model,
                    }
                ),
                parent_id=intent_event_id,
            )

            t0 = time.perf_counter()
            result = await self.runner.run(handle.path)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            kind = Kind.VERIFICATION_PASSED if result.passed else Kind.VERIFICATION_FAILED
            verify_id = await self.ledger.append(
                kind,
                "agent:fused",
                json.dumps(
                    {
                        "branch": handle.branch,
                        "rc": result.rc,
                        "ms": elapsed_ms,
                        "stdout_tail": result.stdout_tail,
                    }
                ),
                parent_id=patch_id,
            )
            return LoopResult(
                ok=result.passed,
                branch=handle.branch,
                worktree=handle.path,
                verification_event_id=verify_id,
            )
        except PatchFormatError as e:
            verify_id = await self.ledger.append(
                Kind.VERIFICATION_FAILED,
                "agent:fused",
                json.dumps({"branch": handle.branch, "error": str(e)}),
                parent_id=intent_event_id,
            )
            return LoopResult(
                ok=False,
                branch=handle.branch,
                worktree=handle.path,
                verification_event_id=verify_id,
            )
