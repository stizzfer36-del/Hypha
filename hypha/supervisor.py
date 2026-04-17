"""Supervisor — the loop that turns an IntentCreated into a merged commit.

Watches the ledger. For each unseen IntentCreated event it runs the
split pipeline:

    Planner -> Coder -> Verifier -> (human approval via ask callback)

Keeps a cursor at `.hypha/supervisor.cursor` so restarts don't replay
history. The supervisor is the only component that creates sub-events for
an intent, so the cursor is the single writer of its own state.

Dependencies are injected so tests can substitute a FakeRouter, an
in-memory ledger, a headless ask(), etc. When `router` is None (no
providers), the supervisor falls back to the fused agent if configured
and logs-and-skips if neither path is available.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from hypha.agents.archivist import Archivist
from hypha.agents.coder import Coder
from hypha.agents.planner import Planner
from hypha.agents.verifier import Verifier
from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.reflection.run_log import Run, RunLog
from hypha.router import Router

log = logging.getLogger("hypha.supervisor")


@dataclass
class SupervisorConfig:
    repo_root: Path
    cursor_path: Path
    run_log_path: Optional[Path] = None
    base_branch: str = "main"
    poll_interval_s: float = 1.0
    max_history_on_start: int = 10


def _read_cursor(path: Path) -> float:
    try:
        return float(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0.0


def _write_cursor(path: Path, ts: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(f"{ts:.6f}\n")
    tmp.replace(path)


class Supervisor:
    def __init__(
        self,
        ledger: Ledger,
        router: Router,
        cfg: SupervisorConfig,
        ask: Callable[[str], bool],
        context_render: Optional[Callable[[str], str]] = None,
    ):
        self.ledger = ledger
        self.router = router
        self.cfg = cfg
        self.ask = ask
        self.context_render = context_render
        self.run_log = RunLog(cfg.run_log_path) if cfg.run_log_path else None
        self._stop = asyncio.Event()
        self._cursor_ts = _read_cursor(cfg.cursor_path)

    def stop(self) -> None:
        self._stop.set()

    async def process_intent(self, intent_event_id: str) -> dict:
        """End-to-end: plan -> code -> verify -> (approve)."""
        start = time.perf_counter()
        planner = Planner(self.ledger, self.router)
        coder = Coder(
            self.ledger,
            self.router,
            self.cfg.repo_root,
            context_render=self.context_render,
        )
        verifier = Verifier(self.ledger)
        archivist = Archivist(
            self.ledger, self.cfg.repo_root, self.ask, run_log=self.run_log
        )

        outcome = {"intent": intent_event_id, "accepted": False}

        plan = await planner.handle(intent_event_id)
        outcome["plan"] = plan.event_id

        submission = await coder.handle(plan.event_id)
        outcome["patch"] = submission.event_id

        verify = await verifier.handle(submission.event_id, submission.worktree)
        outcome["verify"] = verify.event_id

        if verify.passed:
            archive = await archivist.record(
                verify.event_id, base=self.cfg.base_branch
            )
            outcome["decision"] = archive.decision_event_id
            outcome["accepted"] = archive.accepted

        if self.run_log is not None:
            elapsed = int((time.perf_counter() - start) * 1000)
            self.run_log.append(
                Run(
                    agent="supervisor",
                    prompt_id="code",
                    variant_id="baseline",
                    model="router",
                    tokens_in=0,
                    tokens_out=0,
                    verification_passed=verify.passed,
                    ms=elapsed,
                    failure_signature=None if verify.passed else "VerificationFailed",
                )
            )
        return outcome

    async def _drain_once(self) -> int:
        rows = await self.ledger.recent(
            kind=Kind.INTENT_CREATED, limit=self.cfg.max_history_on_start
        )
        # Oldest-first so parent_id chains make sense.
        pending = sorted(
            (r for r in rows if r.ts > self._cursor_ts), key=lambda r: r.ts
        )
        processed = 0
        for r in pending:
            try:
                await self.process_intent(r.id)
            except Exception as e:
                log.exception("intent %s failed: %s", r.id, e)
                await self.ledger.append(
                    Kind.VERIFICATION_FAILED,
                    "supervisor",
                    json.dumps({"intent": r.id, "error": repr(e)[:500]}),
                    parent_id=r.id,
                )
            self._cursor_ts = r.ts
            _write_cursor(self.cfg.cursor_path, self._cursor_ts)
            processed += 1
        return processed

    async def run(self) -> None:
        log.info(
            "supervisor up — cursor=%.3f repo=%s",
            self._cursor_ts, self.cfg.repo_root,
        )
        while not self._stop.is_set():
            await self._drain_once()
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.cfg.poll_interval_s
                )
            except asyncio.TimeoutError:
                pass
        log.info("supervisor down")
