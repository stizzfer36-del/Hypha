"""Pytest plugin — runtime-trace capture.

We invoke pytest-in-pytest against a tiny project and verify spans land in
the RuntimeTraces DB.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import duckdb


def test_plugin_captures_spans_when_env_set(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "test_sample.py").write_text(
        "def test_ok(): assert True\n"
        "def test_bad(): assert False\n"
    )
    (proj / "conftest.py").write_text(
        "import sys, os\n"
        # Put our hypha package on sys.path for the child pytest.
        f"sys.path.insert(0, {str(Path.cwd().resolve())!r})\n"
        "pytest_plugins = ['hypha.verify.pytest_plugin']\n"
    )

    db = tmp_path / "joint.duckdb"
    env = os.environ.copy()
    env["HYPHA_TRACE_DB"] = str(db)
    # Use the same venv's pytest
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(proj),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert db.exists(), "trace DB not created"
    con = duckdb.connect(str(db))
    try:
        rows = con.execute(
            "SELECT func, ok, when_ FROM "
            "(SELECT func, ok, json_extract_string(attrs, '$.when') AS when_ "
            " FROM runtime_spans) WHERE when_ = 'call'"
        ).fetchall()
    finally:
        con.close()

    by_name = {r[0]: r[1] for r in rows}
    # pytest nodeid shape is `test_sample.py::test_ok`
    assert any("test_ok" in k and v for k, v in by_name.items())
    assert any("test_bad" in k and not v for k, v in by_name.items())


def test_plugin_noop_when_env_missing(tmp_path: Path) -> None:
    proj = tmp_path / "proj2"
    proj.mkdir()
    (proj / "test_x.py").write_text("def test_a(): assert True\n")
    (proj / "conftest.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(Path.cwd().resolve())!r})\n"
        "pytest_plugins = ['hypha.verify.pytest_plugin']\n"
    )
    db = tmp_path / "joint.duckdb"
    env = {k: v for k, v in os.environ.items() if k != "HYPHA_TRACE_DB"}
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(proj),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    # No DB should have been created.
    assert not db.exists()
