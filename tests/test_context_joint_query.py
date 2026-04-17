"""M2 — joint query tests.

Build a tiny toy repo in a tmp dir, run AST + git history indexers, and
confirm joint_query ranks the intent-relevant file above the decoy.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
import pytest

from hypha.context.ast_index import ASTIndex
from hypha.context.git_history import GitHistory
from hypha.context.joint_query import JointQuery


def _write_and_commit(
    repo: pygit2.Repository,
    root: Path,
    files: dict[str, str],
    message: str,
) -> str:
    sig = pygit2.Signature("t", "t@t", 1_700_000_000, 0)
    for rel, contents in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
        repo.index.add(rel)
    repo.index.write()
    tree = repo.index.write_tree()
    parents = [repo.head.target] if not repo.head_is_unborn else []
    return str(repo.create_commit("HEAD", sig, sig, message, tree, parents))


@pytest.fixture()
def toy_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "toy"
    repo_dir.mkdir()
    repo = pygit2.init_repository(str(repo_dir), initial_head="main")

    _write_and_commit(
        repo,
        repo_dir,
        {
            "auth.py": (
                "def authenticate(user):\n"
                "    return user\n"
                "\n"
                "class AuthSession:\n"
                "    pass\n"
            ),
            "billing.py": (
                "def charge(amount):\n"
                "    return amount\n"
                "\n"
                "class Invoice:\n"
                "    pass\n"
            ),
        },
        "add auth and billing",
    )

    _write_and_commit(
        repo,
        repo_dir,
        {
            "auth.py": (
                "def authenticate(user):\n"
                "    return user\n"
                "\n"
                "def authorize(user, scope):\n"
                "    return True\n"
                "\n"
                "class AuthSession:\n"
                "    pass\n"
            )
        },
        "add authorize to auth flow",
    )
    return repo_dir


def test_joint_query_prefers_relevant_file(tmp_path: Path, toy_repo: Path) -> None:
    duck = tmp_path / "joint.duckdb"
    ASTIndex(toy_repo, duck).rebuild()
    GitHistory(toy_repo, duck).rebuild()

    slices = JointQuery(duck).query("make auth idempotent", limit=5)
    assert slices, "query returned nothing"
    assert slices[0].path == "auth.py"
    assert slices[0].score > 0
    # rationale should surface what matched
    assert slices[0].rationale["ast_symbols"]
    assert any(
        s.lower().startswith("auth") for s in slices[0].rationale["ast_symbols"]
    )


def test_joint_query_empty_on_no_terms(tmp_path: Path, toy_repo: Path) -> None:
    duck = tmp_path / "joint.duckdb"
    ASTIndex(toy_repo, duck).rebuild()
    GitHistory(toy_repo, duck).rebuild()
    assert JointQuery(duck).query("") == []
    assert JointQuery(duck).query("??") == []


def test_ast_index_counts_symbols(tmp_path: Path, toy_repo: Path) -> None:
    duck = tmp_path / "joint.duckdb"
    n = ASTIndex(toy_repo, duck).rebuild()
    # 2 files * (2 functions-or-classes each) = at least 4; final state of
    # auth.py has 2 functions + 1 class = 3, billing.py has 1 function + 1
    # class = 2; total = 5.
    assert n == 5


def test_ast_index_skips_venv(tmp_path: Path, toy_repo: Path) -> None:
    # Add a file under .venv that looks like a function goldmine.
    venv_dir = toy_repo / ".venv" / "lib"
    venv_dir.mkdir(parents=True)
    (venv_dir / "noise.py").write_text(
        "def one():\n    pass\n\n"
        "def two():\n    pass\n\n"
        "def three():\n    pass\n"
    )
    duck = tmp_path / "joint2.duckdb"
    n = ASTIndex(toy_repo, duck).rebuild()
    # Without .venv skip, n would be 8; with skip, 5.
    assert n == 5


def test_git_history_records_commits(tmp_path: Path, toy_repo: Path) -> None:
    duck = tmp_path / "joint.duckdb"
    n = GitHistory(toy_repo, duck).rebuild()
    assert n == 2
