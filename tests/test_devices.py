"""M7 — multi-device claim + heartbeat tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from hypha.devices.claim import Claim
from hypha.devices.heartbeat import Heartbeat
from hypha.events import Kind
from hypha.ledger import Ledger


async def _ledger(tmp_path: Path) -> Ledger:
    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    return ledger


async def test_single_claim_wins(tmp_path: Path) -> None:
    ledger = await _ledger(tmp_path)
    c = Claim(tmp_path / "claims.db", ledger=ledger)
    assert await c.try_claim("t1", "pi")
    assert c.owner("t1").device_id == "pi"


async def test_second_claim_sees_conflict(tmp_path: Path) -> None:
    c = Claim(tmp_path / "claims.db")
    assert await c.try_claim("t1", "pi")
    assert not await c.try_claim("t1", "chromebook")
    assert c.owner("t1").device_id == "pi"


async def test_concurrent_claim_race(tmp_path: Path) -> None:
    ledger = await _ledger(tmp_path)
    c = Claim(tmp_path / "claims.db", ledger=ledger)

    async def claim(dev: str) -> bool:
        return await c.try_claim("race", dev)

    # Fire many in parallel; exactly one must win.
    results = await asyncio.gather(*(claim(f"d{i}") for i in range(20)))
    assert results.count(True) == 1
    owner = c.owner("race")
    assert owner is not None


async def test_release_only_by_owner(tmp_path: Path) -> None:
    c = Claim(tmp_path / "claims.db")
    assert await c.try_claim("t1", "pi")
    # Some other device cannot release.
    assert not await c.release("t1", "chromebook")
    assert c.owner("t1") is not None
    # Owner can release.
    assert await c.release("t1", "pi")
    assert c.owner("t1") is None


async def test_heartbeat_writes_row(tmp_path: Path) -> None:
    # A Claim must exist first so the heartbeats schema is set up.
    Claim(tmp_path / "shared.db")
    hb = Heartbeat(device_id="pi", tags=["always-on", "gpu"], path=tmp_path / "shared.db")
    ts = hb.beat_once()
    import sqlite3

    with sqlite3.connect(str(tmp_path / "shared.db")) as db:
        row = db.execute(
            "SELECT device_id, last_seen_ts, tags FROM heartbeats WHERE device_id = ?",
            ("pi",),
        ).fetchone()
    assert row is not None
    assert row[0] == "pi"
    assert row[1] == pytest.approx(ts, abs=1.0)
    assert set(json.loads(row[2])) == {"always-on", "gpu"}


async def test_stale_heartbeat_releases_claim(tmp_path: Path) -> None:
    ledger = await _ledger(tmp_path)
    c = Claim(tmp_path / "shared.db", ledger=ledger)
    hb = Heartbeat(device_id="pi", tags=["always-on"], path=tmp_path / "shared.db")
    hb.beat_once()
    assert await c.try_claim("t1", "pi")

    # Force last_seen_ts into the deep past.
    import sqlite3, time as _t

    with sqlite3.connect(str(tmp_path / "shared.db")) as db:
        db.execute(
            "UPDATE heartbeats SET last_seen_ts = ? WHERE device_id = ?",
            (_t.time() - 3600.0, "pi"),
        )

    released = await c.release_stale(heartbeat_timeout_s=300.0)
    assert "t1" in released
    assert c.owner("t1") is None

    # Ledger received a TaskReleased event with reason=stale.
    rows = await ledger.recent(kind=Kind.TASK_RELEASED, limit=5)
    assert rows
    payload = json.loads(rows[0].payload)
    assert payload.get("reason") == "stale" or payload.get("former_device") == "pi"
