"""CLI smoke tests — accept/reject/events via typer's test runner."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hypha.cli import app
from hypha.events import Kind
from hypha.ledger import Ledger


@pytest.fixture()
def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "hypha.db"
    monkeypatch.setenv("HYPHA_DB_PATH", str(db))
    return db


def test_intent_then_events(db_env: Path) -> None:
    runner = CliRunner()
    r1 = runner.invoke(app, ["intent", "hello world"])
    assert r1.exit_code == 0
    assert r1.stdout.strip()  # echoed event id
    r2 = runner.invoke(app, ["events", "--limit", "5"])
    assert r2.exit_code == 0
    assert "hello world" in r2.stdout


def test_accept_rejects_missing_event(db_env: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["accept", "nosuchevent"])
    assert r.exit_code != 0
    assert "no VerificationPassed" in r.stdout


def test_accept_records_decision(db_env: Path) -> None:
    # seed a VerificationPassed we can target by prefix
    async def seed() -> str:
        ledger = Ledger(str(db_env))
        await ledger.init()
        return await ledger.append(
            Kind.VERIFICATION_PASSED, "agent", json.dumps({"branch": "b"})
        )

    vid = asyncio.run(seed())
    runner = CliRunner()
    r = runner.invoke(app, ["accept", vid[:8]])
    assert r.exit_code == 0
    assert "accepted" in r.stdout

    async def check() -> None:
        ledger = Ledger(str(db_env))
        await ledger.init()
        rows = await ledger.recent(kind=Kind.DECISION_RECORDED, limit=1)
        assert rows and json.loads(rows[0].payload)["accepted"] is True

    asyncio.run(check())


def test_status_reports_no_daemon(db_env: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 0
    assert "daemon" in r.stdout
