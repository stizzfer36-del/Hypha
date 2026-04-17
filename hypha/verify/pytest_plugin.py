"""M8 — pytest plugin that captures span data into RuntimeTraces.

Enable by setting HYPHA_TRACE_DB=/abs/path/to/joint.duckdb when invoking
pytest; the plugin auto-enables when the env var is present.

Span shape:
    {"path": <test file>, "func": <test name>, "ts": <when>,
     "ok": <bool>, "attrs": {"duration_s": <float>, "when": <phase>}}

Phase is pytest's "call" (the test body). Setup/teardown errors are still
recorded but attributed to "setup"/"teardown".
"""

from __future__ import annotations

import os
import time
from pathlib import Path

try:  # pragma: no cover - pytest is a dev/extras dep
    import pytest
except ImportError:  # pragma: no cover
    pytest = None  # type: ignore[assignment]

from hypha.context.runtime_traces import RuntimeTraces


_ENV_VAR = "HYPHA_TRACE_DB"
_collected: list[dict] = []


def pytest_configure(config) -> None:  # pragma: no cover - pytest hook
    config._hypha_trace_db = os.environ.get(_ENV_VAR)


def pytest_runtest_makereport(item, call):  # pragma: no cover - pytest hook
    if not os.environ.get(_ENV_VAR):
        return
    # Only record final outcome per phase.
    _collected.append(
        {
            "path": str(Path(item.fspath).resolve()),
            "func": item.nodeid,
            "ts": time.time(),
            "ok": call.excinfo is None,
            "attrs": {
                "duration_s": round(call.duration, 6),
                "when": call.when,
            },
        }
    )


def pytest_sessionfinish(session, exitstatus) -> None:  # pragma: no cover
    db = os.environ.get(_ENV_VAR)
    if not db or not _collected:
        return
    try:
        RuntimeTraces(Path(db)).ingest(_collected)
    finally:
        _collected.clear()
