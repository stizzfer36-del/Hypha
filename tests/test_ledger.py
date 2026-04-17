"""M1 — ledger tests.

Covers:
  - schema creation idempotent
  - append -> recent round-trip
  - kind filter
  - persistence across reconnect (WAL)
  - rejects a directory path
  - creates missing parent directory
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hypha.ledger import Ledger


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "hypha.db")


async def test_init_idempotent(db_path: str) -> None:
    ledger = Ledger(db_path)
    await ledger.init()
    await ledger.init()  # second call must not raise


async def test_append_then_recent(db_path: str) -> None:
    ledger = Ledger(db_path)
    await ledger.init()
    eid = await ledger.append("IntentCreated", "cli:user", json.dumps({"text": "hi"}))
    assert eid
    rows = await ledger.recent()
    assert len(rows) == 1
    assert rows[0].id == eid
    assert rows[0].kind == "IntentCreated"
    assert rows[0].actor == "cli:user"
    assert json.loads(rows[0].payload)["text"] == "hi"


async def test_recent_kind_filter(db_path: str) -> None:
    ledger = Ledger(db_path)
    await ledger.init()
    await ledger.append("IntentCreated", "a", "{}")
    await ledger.append("DaemonStarted", "b", "{}")
    await ledger.append("IntentCreated", "c", "{}")
    intents = await ledger.recent(kind="IntentCreated")
    assert len(intents) == 2
    assert {r.actor for r in intents} == {"a", "c"}


async def test_persistence_across_reconnect(db_path: str) -> None:
    ledger1 = Ledger(db_path)
    await ledger1.init()
    eid = await ledger1.append("IntentCreated", "cli", "{}")

    ledger2 = Ledger(db_path)
    await ledger2.init()
    rows = await ledger2.recent()
    assert any(r.id == eid for r in rows)


async def test_parent_id_persists(db_path: str) -> None:
    ledger = Ledger(db_path)
    await ledger.init()
    parent = await ledger.append("IntentCreated", "cli", "{}")
    child = await ledger.append("PlanProposed", "agent", "{}", parent_id=parent)
    rows = await ledger.recent(kind="PlanProposed")
    assert rows[0].id == child
    assert rows[0].parent_id == parent


def test_rejects_directory_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Ledger(str(tmp_path))  # tmp_path is a directory


def test_creates_missing_parent(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nest" / "hypha.db"
    ledger = Ledger(str(nested))
    assert os.path.isdir(nested.parent)
    assert ledger.path == str(nested.resolve())
