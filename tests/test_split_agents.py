"""Tests for split-role agents + behavioral diff + supervisor end-to-end."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pygit2
import pytest

from hypha.agents.archivist import Archivist
from hypha.agents.coder import Coder
from hypha.agents.planner import Planner, PlannerError
from hypha.agents.verifier import Verifier
from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.router import Request, Response
from hypha.supervisor import Supervisor, SupervisorConfig
from hypha.verify.behavioral_diff import BehavioralDiff, _run_pytest_with_junit


@dataclass
class Scripted:
    """A router that returns pre-scripted responses based on capability."""

    by_capability: dict[str, str]

    async def call(self, req: Request) -> Response:
        text = self.by_capability.get(req.capability, "{}")
        return Response(
            text=text,
            provider="scripted",
            model="m",
            tokens_in=len(req.prompt),
            tokens_out=len(text),
            ms=0,
        )


def _init_toy_with_failing_test(root: Path) -> pygit2.Repository:
    """Creates a repo whose tests currently fail (mymod.answer missing)."""
    repo = pygit2.init_repository(str(root), initial_head="main")
    sig = pygit2.Signature("t", "t@t", 1_700_000_000, 0)
    (root / "tests").mkdir()
    (root / "tests" / "test_answer.py").write_text(
        "from mymod import answer\n"
        "def test_answer():\n"
        "    assert answer() == 42\n"
    )
    (root / "conftest.py").write_text(
        "import sys, pathlib\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).parent))\n"
    )
    repo.index.add("tests/test_answer.py")
    repo.index.add("conftest.py")
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("HEAD", sig, sig, "init", tree, [])
    return repo


# ---- Planner -----------------------------------------------------------------


async def test_planner_decomposes_intent(tmp_path: Path) -> None:
    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    intent_id = await ledger.append(
        Kind.INTENT_CREATED, "cli:t", json.dumps({"text": "add helper"})
    )
    router = Scripted(by_capability={
        "plan": json.dumps({"subgoals": ["create mymod.py", "expose answer()"]}),
    })
    plan = await Planner(ledger, router).handle(intent_id)
    assert len(plan.subgoals) == 2
    rows = await ledger.recent(kind=Kind.PLAN_PROPOSED, limit=1)
    assert rows and rows[0].parent_id == intent_id


async def test_planner_rejects_malformed(tmp_path: Path) -> None:
    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    intent_id = await ledger.append(
        Kind.INTENT_CREATED, "cli:t", json.dumps({"text": "x"})
    )
    router = Scripted(by_capability={"plan": "not json"})
    with pytest.raises(PlannerError):
        await Planner(ledger, router).handle(intent_id)


# ---- Coder -------------------------------------------------------------------


async def test_coder_writes_submission(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    root.mkdir()
    _init_toy_with_failing_test(root)

    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    plan_id = await ledger.append(
        Kind.PLAN_PROPOSED,
        "agent:planner",
        json.dumps({"intent": "x", "subgoals": ["write mymod"]}),
    )
    router = Scripted(by_capability={
        "code": json.dumps({"files": {"mymod.py": "def answer():\n    return 42\n"}}),
    })
    sub = await Coder(ledger, router, root).handle(plan_id)
    assert sub.files == ["mymod.py"]
    # Worktree actually contains the file.
    assert (sub.worktree / "mymod.py").exists()


async def test_coder_records_patch_error_on_bad_json(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    root.mkdir()
    _init_toy_with_failing_test(root)

    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    plan_id = await ledger.append(
        Kind.PLAN_PROPOSED,
        "agent:planner",
        json.dumps({"intent": "x", "subgoals": ["write mymod"]}),
    )
    router = Scripted(by_capability={"code": "no JSON here"})
    sub = await Coder(ledger, router, root).handle(plan_id)
    assert sub.files == []
    rows = await ledger.recent(kind=Kind.PATCH_SUBMITTED, limit=1)
    assert rows and "error" in rows[0].payload


# ---- Verifier ----------------------------------------------------------------


async def test_verifier_passes_on_good_patch(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    root.mkdir()
    _init_toy_with_failing_test(root)

    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    plan_id = await ledger.append(
        Kind.PLAN_PROPOSED,
        "agent:planner",
        json.dumps({"intent": "x", "subgoals": ["write mymod"]}),
    )
    router = Scripted(by_capability={
        "code": json.dumps({"files": {"mymod.py": "def answer():\n    return 42\n"}}),
    })
    sub = await Coder(ledger, router, root).handle(plan_id)
    verify = await Verifier(ledger).handle(sub.event_id, sub.worktree)
    assert verify.passed
    assert verify.mypy_ok  # no mypy configured -> not a failure
    rows = await ledger.recent(kind=Kind.VERIFICATION_PASSED, limit=1)
    assert rows and rows[0].parent_id == sub.event_id


async def test_verifier_fails_on_bad_patch(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    root.mkdir()
    _init_toy_with_failing_test(root)

    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    plan_id = await ledger.append(
        Kind.PLAN_PROPOSED, "agent:planner",
        json.dumps({"intent": "x", "subgoals": ["bad"]}),
    )
    router = Scripted(by_capability={
        "code": json.dumps({"files": {"mymod.py": "def answer():\n    return 41\n"}}),
    })
    sub = await Coder(ledger, router, root).handle(plan_id)
    verify = await Verifier(ledger).handle(sub.event_id, sub.worktree)
    assert not verify.passed
    rows = await ledger.recent(kind=Kind.VERIFICATION_FAILED, limit=1)
    assert rows


# ---- Behavioral diff ---------------------------------------------------------


def test_run_pytest_with_junit_parses_outcomes(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "test_stuff.py").write_text(
        "def test_ok(): assert True\n"
        "def test_bad(): assert False\n"
    )
    outcomes, ms = _run_pytest_with_junit(root, pytest_bin="pytest")
    names = {o.name: o.passed for o in outcomes}
    # The actual classname pytest assigns varies, but the func name is preserved.
    assert any(name.endswith("test_ok") and ok for name, ok in names.items())
    assert any(name.endswith("test_bad") and not ok for name, ok in names.items())


async def test_behavioral_diff_detects_regression(tmp_path: Path) -> None:
    # pre: 2/2 passing.
    pre = tmp_path / "pre"
    pre.mkdir()
    (pre / "test_stuff.py").write_text(
        "def test_a(): assert True\n"
        "def test_b(): assert True\n"
    )
    # post: a regresses.
    post = tmp_path / "post"
    post.mkdir()
    (post / "test_stuff.py").write_text(
        "def test_a(): assert False  # regression!\n"
        "def test_b(): assert True\n"
    )
    diff = await BehavioralDiff().run(pre, post)
    assert diff.divergent
    assert any("test_a" in p for p in diff.properties)


async def test_behavioral_diff_accepts_improvements(tmp_path: Path) -> None:
    pre = tmp_path / "pre"
    pre.mkdir()
    (pre / "test_stuff.py").write_text(
        "def test_a(): assert False\n"
        "def test_b(): assert True\n"
    )
    post = tmp_path / "post"
    post.mkdir()
    (post / "test_stuff.py").write_text(
        "def test_a(): assert True\n"
        "def test_b(): assert True\n"
    )
    diff = await BehavioralDiff().run(pre, post)
    assert not diff.divergent
    assert diff.improvements


# ---- Archivist ---------------------------------------------------------------


async def test_archivist_accepts_and_merges(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    root.mkdir()
    repo = _init_toy_with_failing_test(root)
    # Create a feature branch that ff-merges cleanly.
    base = repo.head.target
    repo.branches.local.create("hypha/task", repo[base])
    repo.checkout("refs/heads/hypha/task")
    (root / "mymod.py").write_text("def answer():\n    return 42\n")
    repo.index.add("mymod.py"); repo.index.write()
    sig = pygit2.Signature("t", "t@t", 1_700_000_100, 0)
    repo.create_commit("HEAD", sig, sig, "feat", repo.index.write_tree(), [base])
    repo.checkout("refs/heads/main")

    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    vid = await ledger.append(
        Kind.VERIFICATION_PASSED, "agent:verifier",
        json.dumps({"branch": "hypha/task"}),
    )
    arch = Archivist(ledger, root, ask=lambda diff: True)
    result = await arch.record(vid, base="main")
    assert result.accepted
    assert (root / "mymod.py").exists()


# ---- Supervisor end-to-end ---------------------------------------------------


async def test_supervisor_drains_intents(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    root.mkdir()
    _init_toy_with_failing_test(root)

    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    intent_id = await ledger.append(
        Kind.INTENT_CREATED, "cli:t", json.dumps({"text": "add answer"})
    )
    router = Scripted(by_capability={
        "plan": json.dumps({"subgoals": ["write mymod with answer()"]}),
        "code": json.dumps({"files": {"mymod.py": "def answer():\n    return 42\n"}}),
    })
    sup_cfg = SupervisorConfig(
        repo_root=root,
        cursor_path=tmp_path / "cursor",
        run_log_path=tmp_path / "runs.db",
        base_branch="main",
    )
    sup = Supervisor(ledger, router, sup_cfg, ask=lambda diff: True)

    # Run _drain_once directly instead of the loop.
    processed = await sup._drain_once()
    assert processed == 1

    kinds = [r.kind for r in await ledger.recent(limit=20)]
    for expected in (
        "IntentCreated", "PlanProposed", "PatchSubmitted",
        "VerificationPassed", "DecisionRecorded",
    ):
        assert expected in kinds, f"missing {expected}; saw {kinds}"

    # Cursor advanced to the intent's ts, so a re-drain is a no-op.
    again = await sup._drain_once()
    assert again == 0


async def test_supervisor_resumes_from_cursor(tmp_path: Path) -> None:
    """Write a cursor in the future; supervisor must skip earlier intents."""
    root = tmp_path / "toy"
    root.mkdir()
    _init_toy_with_failing_test(root)

    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    await ledger.append(Kind.INTENT_CREATED, "cli:t", json.dumps({"text": "old"}))

    cursor_path = tmp_path / "cursor"
    import time as _t
    cursor_path.write_text(f"{_t.time() + 100:.6f}\n")

    sup_cfg = SupervisorConfig(
        repo_root=root,
        cursor_path=cursor_path,
        base_branch="main",
    )
    router = Scripted(by_capability={})
    sup = Supervisor(ledger, router, sup_cfg, ask=lambda diff: False)
    processed = await sup._drain_once()
    assert processed == 0
