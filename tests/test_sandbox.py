"""M5 — sandbox + diff approval tests.

Firejail tests are unit-level (argv construction, cwd-escape refusal) because
firejail itself may not be installed in every environment. The diff-approval
tests use a real pygit2-initialized repo + a stub `ask()` callback.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pygit2
import pytest

from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.sandbox.firejail import (
    DEFAULT_PROFILE,
    Firejail,
    FirejailError,
    build_argv,
    _timeout_hms,
)
from hypha.surface.diff_approval import DiffApproval, render_diff


def test_timeout_formatting() -> None:
    assert _timeout_hms(0) == "00:00:00"
    assert _timeout_hms(65) == "00:01:05"
    assert _timeout_hms(3725) == "01:02:05"


def test_build_argv_includes_hardening() -> None:
    argv = build_argv("/usr/bin/firejail", DEFAULT_PROFILE, Path("/tmp/x"), ["pytest"], 60)
    assert argv[0] == "/usr/bin/firejail"
    assert "--net=none" in argv
    assert f"--profile={DEFAULT_PROFILE}" in argv
    assert "--" in argv
    assert argv[argv.index("--") + 1 :] == ["pytest"]


def test_firejail_refuses_missing_profile(tmp_path: Path) -> None:
    with pytest.raises(FirejailError, match="profile not found"):
        Firejail(profile=tmp_path / "nope.profile")


async def test_firejail_refuses_cwd_outside_worktrees(tmp_path: Path) -> None:
    fj = Firejail(profile=DEFAULT_PROFILE)
    with pytest.raises(FirejailError, match="worktrees"):
        await fj.run(["echo", "x"], cwd=tmp_path)


async def test_firejail_detects_missing_binary(tmp_path: Path) -> None:
    wt = tmp_path / ".hypha" / "worktrees" / "a1b2"
    wt.mkdir(parents=True)
    fj = Firejail(profile=DEFAULT_PROFILE)
    with patch("hypha.sandbox.firejail.shutil.which", return_value=None):
        with pytest.raises(FirejailError, match="not installed"):
            await fj.run(["echo", "x"], cwd=wt)


# ---- DiffApproval ------------------------------------------------------------


def _init_repo_with_main_branch(root: Path) -> pygit2.Repository:
    repo = pygit2.init_repository(str(root), initial_head="main")
    sig = pygit2.Signature("t", "t@t", 1_700_000_000, 0)
    (root / "README.md").write_text("hi\n")
    repo.index.add("README.md")
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("HEAD", sig, sig, "init", tree, [])
    return repo


async def test_approval_accept_merges_ff(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    repo = _init_repo_with_main_branch(root)

    # Make a feature branch that fast-forwards cleanly.
    base = repo.head.target
    repo.branches.local.create("feature", repo[base])
    repo.checkout("refs/heads/feature")
    (root / "new.txt").write_text("feature\n")
    repo.index.add("new.txt")
    repo.index.write()
    sig = pygit2.Signature("t", "t@t", 1_700_000_100, 0)
    tree = repo.index.write_tree()
    repo.create_commit("HEAD", sig, sig, "feat", tree, [base])
    repo.checkout("refs/heads/main")

    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    vid = await ledger.append(Kind.VERIFICATION_PASSED, "agent", "{}")
    approval = DiffApproval(ledger=ledger, repo_root=root, ask=lambda diff: True)

    decision = await approval.request(vid, branch="feature", base="main")
    assert decision.accepted
    # After ff merge, main's HEAD should contain new.txt
    assert (root / "new.txt").exists()
    rows = await ledger.recent(kind=Kind.DECISION_RECORDED, limit=1)
    assert rows and json.loads(rows[0].payload)["accepted"] is True


async def test_approval_reject_does_not_merge(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    repo = _init_repo_with_main_branch(root)
    base = repo.head.target
    repo.branches.local.create("feature", repo[base])
    repo.checkout("refs/heads/feature")
    (root / "new.txt").write_text("feature\n")
    repo.index.add("new.txt")
    repo.index.write()
    sig = pygit2.Signature("t", "t@t", 1_700_000_100, 0)
    tree = repo.index.write_tree()
    repo.create_commit("HEAD", sig, sig, "feat", tree, [base])
    repo.checkout("refs/heads/main")

    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    vid = await ledger.append(Kind.VERIFICATION_PASSED, "agent", "{}")
    approval = DiffApproval(ledger=ledger, repo_root=root, ask=lambda diff: False)

    decision = await approval.request(vid, branch="feature", base="main")
    assert not decision.accepted
    assert not (root / "new.txt").exists()


def test_render_diff_shows_changes(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    repo = _init_repo_with_main_branch(root)
    base = repo.head.target
    repo.branches.local.create("feature", repo[base])
    repo.checkout("refs/heads/feature")
    (root / "new.txt").write_text("feature\n")
    repo.index.add("new.txt")
    repo.index.write()
    sig = pygit2.Signature("t", "t@t", 1_700_000_100, 0)
    tree = repo.index.write_tree()
    repo.create_commit("HEAD", sig, sig, "feat", tree, [base])
    repo.checkout("refs/heads/main")

    diff = render_diff(root, "feature", base="main")
    assert "new.txt" in diff
