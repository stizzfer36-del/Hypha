"""M3 — plan-code-verify loop tests.

Uses a FakeRouter that returns scripted JSON patches. Sets up a toy repo
with a failing test pre-patch; after the loop applies the canned fix,
pytest passes on the worktree branch and the ledger records a
VerificationPassed event. A second scenario with a bad patch records
VerificationFailed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pygit2
import pytest

from hypha.agents.fused import FusedAgent
from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.router import Request, Response


@dataclass
class FakeRouter:
    text: str

    async def call(self, req: Request) -> Response:
        return Response(
            text=self.text,
            provider="fake",
            model="fake-1",
            tokens_in=len(req.prompt),
            tokens_out=len(self.text),
            ms=1,
        )


def _init_toy_repo(root: Path, initial: dict[str, str]) -> pygit2.Repository:
    repo = pygit2.init_repository(str(root), initial_head="main")
    sig = pygit2.Signature("t", "t@t", 1_700_000_000, 0)
    for rel, body in initial.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body)
        repo.index.add(rel)
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("HEAD", sig, sig, "init", tree, [])
    return repo


@pytest.fixture()
def toy_repo(tmp_path: Path) -> Path:
    root = tmp_path / "toy"
    root.mkdir()
    _init_toy_repo(
        root,
        {
            "tests/test_answer.py": (
                "from mymod import answer\n"
                "def test_answer():\n"
                "    assert answer() == 42\n"
            ),
            "conftest.py": 'import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent))\n',
        },
    )
    return root


async def test_loop_passes_with_good_patch(tmp_path: Path, toy_repo: Path) -> None:
    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    intent_id = await ledger.append(
        Kind.INTENT_CREATED, "cli:t", json.dumps({"text": "make answer() return 42"})
    )
    good = json.dumps({"files": {"mymod.py": "def answer():\n    return 42\n"}})
    agent = FusedAgent(ledger=ledger, router=FakeRouter(text=good), repo_root=toy_repo)
    result = await agent.handle(intent_id)
    assert result.ok
    # Ledger records the expected sequence.
    kinds = [r.kind for r in await ledger.recent(limit=10)]
    assert "VerificationPassed" in kinds
    assert "PatchSubmitted" in kinds
    assert "PlanProposed" in kinds


async def test_loop_fails_with_bad_patch(tmp_path: Path, toy_repo: Path) -> None:
    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    intent_id = await ledger.append(
        Kind.INTENT_CREATED, "cli:t", json.dumps({"text": "make answer() return 42"})
    )
    bad = json.dumps({"files": {"mymod.py": "def answer():\n    return 41\n"}})
    agent = FusedAgent(ledger=ledger, router=FakeRouter(text=bad), repo_root=toy_repo)
    result = await agent.handle(intent_id)
    assert not result.ok
    kinds = [r.kind for r in await ledger.recent(limit=10)]
    assert "VerificationFailed" in kinds
    assert "VerificationPassed" not in kinds


async def test_loop_rejects_path_traversal(tmp_path: Path, toy_repo: Path) -> None:
    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    intent_id = await ledger.append(
        Kind.INTENT_CREATED, "cli:t", json.dumps({"text": "traversal attempt"})
    )
    evil = json.dumps({"files": {"../outside.py": "x=1\n"}})
    agent = FusedAgent(ledger=ledger, router=FakeRouter(text=evil), repo_root=toy_repo)
    result = await agent.handle(intent_id)
    assert not result.ok
    failed = await ledger.recent(kind=Kind.VERIFICATION_FAILED, limit=1)
    assert failed
    assert "unsafe path" in failed[0].payload.lower()


async def test_loop_rejects_non_json_response(tmp_path: Path, toy_repo: Path) -> None:
    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    intent_id = await ledger.append(
        Kind.INTENT_CREATED, "cli:t", json.dumps({"text": "dunno"})
    )
    agent = FusedAgent(
        ledger=ledger,
        router=FakeRouter(text="here is some prose, not json"),
        repo_root=toy_repo,
    )
    result = await agent.handle(intent_id)
    assert not result.ok
