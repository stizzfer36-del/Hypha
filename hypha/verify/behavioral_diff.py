"""M3/M5 — behavioral diff via replayed tests.

Role: guard against "tests pass but intent violated". Runs pytest on both
the pre-patch (baseline) and post-patch worktrees, compares per-test
outcomes, flags divergence:

  regressions   = tests that passed on `pre` and fail on `post`
  improvements  = tests that failed on `pre` and pass on `post`
  unchanged     = same outcome in both

`DiffResult.divergent` is True iff any regression exists. Improvements do
not make a diff "divergent" — they're the whole point of a patch. New
tests (present only in `post`) are counted as improvements if they pass,
regressions if they fail (since the patch chose to add a failing test).

JUnit XML is the exchange format; pytest writes it with `--junit-xml=...`.
If the pre-run has no pytest (empty repo), the diff is "no baseline"
and returns divergent=False, properties=[].
"""

from __future__ import annotations

import asyncio
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass
class TestOutcome:
    name: str
    passed: bool


@dataclass
class DiffResult:
    divergent: bool
    properties: list[str] = field(default_factory=list)  # regressed test ids
    improvements: list[str] = field(default_factory=list)
    unchanged: int = 0
    pre_ms: int = 0
    post_ms: int = 0
    note: str = ""


def _run_pytest_with_junit(cwd: Path, pytest_bin: str = "pytest") -> tuple[list[TestOutcome], int]:
    """Runs pytest in `cwd` emitting JUnit XML. Returns (outcomes, ms).
    `-p no:cacheprovider` keeps the pre/post runs from sharing cache state."""
    with NamedTemporaryFile(suffix=".xml", delete=False) as xml_tmp:
        xml_path = xml_tmp.name
    t0 = time.perf_counter()
    try:
        subprocess.run(
            [pytest_bin, "-q", "-p", "no:cacheprovider", f"--junit-xml={xml_path}"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        ms = int((time.perf_counter() - t0) * 1000)
        outcomes: list[TestOutcome] = []
        try:
            tree = ET.parse(xml_path)
        except (ET.ParseError, FileNotFoundError):
            return [], ms
        root = tree.getroot()
        # Accept both <testsuite> root and <testsuites> wrapper.
        suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
        for suite in suites:
            for case in suite.findall("testcase"):
                name = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
                failed = any(
                    case.find(tag) is not None
                    for tag in ("failure", "error")
                )
                outcomes.append(TestOutcome(name=name, passed=not failed))
        return outcomes, ms
    finally:
        try:
            Path(xml_path).unlink()
        except OSError:
            pass


class BehavioralDiff:
    def __init__(self, pytest_bin: str = "pytest"):
        self.pytest_bin = pytest_bin

    async def run(self, pre: Path, post: Path) -> DiffResult:
        pre = Path(pre).resolve()
        post = Path(post).resolve()

        pre_outcomes, pre_ms = await asyncio.to_thread(
            _run_pytest_with_junit, pre, self.pytest_bin
        )
        post_outcomes, post_ms = await asyncio.to_thread(
            _run_pytest_with_junit, post, self.pytest_bin
        )

        if not pre_outcomes and not post_outcomes:
            return DiffResult(divergent=False, pre_ms=pre_ms, post_ms=post_ms,
                              note="no tests collected pre or post")

        pre_map = {o.name: o.passed for o in pre_outcomes}
        post_map = {o.name: o.passed for o in post_outcomes}

        regressions: list[str] = []
        improvements: list[str] = []
        unchanged = 0
        for name, post_ok in post_map.items():
            pre_ok = pre_map.get(name)
            if pre_ok is None:
                # New test — count on the post side.
                (improvements if post_ok else regressions).append(name)
            elif pre_ok and not post_ok:
                regressions.append(name)
            elif not pre_ok and post_ok:
                improvements.append(name)
            else:
                unchanged += 1

        for name, pre_ok in pre_map.items():
            if name in post_map:
                continue
            # Removed test — if it was passing, that's a regression.
            if pre_ok:
                regressions.append(f"(removed) {name}")

        return DiffResult(
            divergent=bool(regressions),
            properties=regressions,
            improvements=improvements,
            unchanged=unchanged,
            pre_ms=pre_ms,
            post_ms=post_ms,
        )
