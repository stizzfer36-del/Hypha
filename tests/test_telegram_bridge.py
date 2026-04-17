"""Telegram bridge — handler-level tests with fake Update/Context."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from hypha.config import Config
from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.telegram_bridge import TelegramBridge


@dataclass
class FakeUser:
    id: int = 7
    username: str | None = "op"


@dataclass
class FakeChat:
    id: int = 42


@dataclass
class FakeMessage:
    text: str = ""
    replies: list[str] = field(default_factory=list)

    async def reply_text(self, text: str, **_: Any) -> None:
        self.replies.append(text)


@dataclass
class FakeUpdate:
    chat_id: int = 42
    user: FakeUser = field(default_factory=FakeUser)
    message: FakeMessage = field(default_factory=FakeMessage)

    @property
    def effective_chat(self):
        return FakeChat(id=self.chat_id)

    @property
    def effective_user(self):
        return self.user


@dataclass
class FakeContext:
    args: list[str] = field(default_factory=list)


def _cfg(tmp_path: Path) -> Config:
    return Config(
        db_path=tmp_path / "ledger.db",
        telegram_bot_token="TOKEN",
        telegram_chat_id="42",
        redis_url=None,
        groq_api_key=None,
        gemini_api_key=None,
        deepseek_api_key=None,
        openrouter_api_key=None,
    )


async def _ledger(tmp_path: Path) -> Ledger:
    ledger = Ledger(str(tmp_path / "ledger.db"))
    await ledger.init()
    return ledger


async def test_intent_writes_to_ledger(tmp_path: Path) -> None:
    ledger = await _ledger(tmp_path)
    bridge = TelegramBridge(_cfg(tmp_path), ledger)
    update = FakeUpdate(message=FakeMessage(text="/intent make auth idempotent"))
    ctx = FakeContext(args=["make", "auth", "idempotent"])
    await bridge.handle_intent(update, ctx)  # type: ignore[arg-type]
    rows = await ledger.recent(kind=Kind.INTENT_CREATED, limit=1)
    assert rows
    assert json.loads(rows[0].payload)["text"] == "make auth idempotent"
    assert rows[0].actor.startswith("telegram:")
    assert update.message.replies and "ok" in update.message.replies[0]


async def test_intent_rejected_for_wrong_chat(tmp_path: Path) -> None:
    ledger = await _ledger(tmp_path)
    bridge = TelegramBridge(_cfg(tmp_path), ledger)
    update = FakeUpdate(chat_id=999, message=FakeMessage(text="/intent hack"))
    ctx = FakeContext(args=["hack"])
    await bridge.handle_intent(update, ctx)  # type: ignore[arg-type]
    rows = await ledger.recent(kind=Kind.INTENT_CREATED, limit=1)
    assert not rows
    assert update.message.replies == []  # silent drop


async def test_events_command_lists_recent(tmp_path: Path) -> None:
    ledger = await _ledger(tmp_path)
    bridge = TelegramBridge(_cfg(tmp_path), ledger)
    await ledger.append(Kind.INTENT_CREATED, "cli:t", "{}")
    await ledger.append(Kind.PLAN_PROPOSED, "agent:planner", "{}")
    update = FakeUpdate(message=FakeMessage())
    ctx = FakeContext(args=[])
    await bridge.handle_events(update, ctx)  # type: ignore[arg-type]
    assert update.message.replies
    body = update.message.replies[0]
    assert "IntentCreated" in body and "PlanProposed" in body


async def test_accept_records_decision(tmp_path: Path) -> None:
    ledger = await _ledger(tmp_path)
    bridge = TelegramBridge(_cfg(tmp_path), ledger)
    vid = await ledger.append(Kind.VERIFICATION_PASSED, "agent", json.dumps({"branch": "b"}))
    update = FakeUpdate(message=FakeMessage())
    ctx = FakeContext(args=[vid[:8]])
    await bridge.handle_accept(update, ctx)  # type: ignore[arg-type]
    rows = await ledger.recent(kind=Kind.DECISION_RECORDED, limit=1)
    assert rows
    assert json.loads(rows[0].payload)["accepted"] is True
    assert rows[0].parent_id == vid


async def test_reject_records_decision(tmp_path: Path) -> None:
    ledger = await _ledger(tmp_path)
    bridge = TelegramBridge(_cfg(tmp_path), ledger)
    vid = await ledger.append(Kind.VERIFICATION_PASSED, "agent", json.dumps({"branch": "b"}))
    update = FakeUpdate(message=FakeMessage())
    ctx = FakeContext(args=[vid[:8]])
    await bridge.handle_reject(update, ctx)  # type: ignore[arg-type]
    rows = await ledger.recent(kind=Kind.DECISION_RECORDED, limit=1)
    assert rows
    assert json.loads(rows[0].payload)["accepted"] is False


async def test_accept_with_unknown_prefix_does_nothing(tmp_path: Path) -> None:
    ledger = await _ledger(tmp_path)
    bridge = TelegramBridge(_cfg(tmp_path), ledger)
    update = FakeUpdate(message=FakeMessage())
    ctx = FakeContext(args=["nosuch"])
    await bridge.handle_accept(update, ctx)  # type: ignore[arg-type]
    rows = await ledger.recent(kind=Kind.DECISION_RECORDED, limit=1)
    assert not rows
    assert "no VerificationPassed" in update.message.replies[0]


def test_missing_token_refuses_construction(tmp_path: Path) -> None:
    cfg = Config(
        db_path=tmp_path / "ledger.db",
        telegram_bot_token=None,
        telegram_chat_id="42",
        redis_url=None,
        groq_api_key=None, gemini_api_key=None,
        deepseek_api_key=None, openrouter_api_key=None,
    )
    ledger = Ledger(str(tmp_path / "ledger.db"))
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        TelegramBridge(cfg, ledger)


def test_missing_chat_id_refuses_construction(tmp_path: Path) -> None:
    cfg = Config(
        db_path=tmp_path / "ledger.db",
        telegram_bot_token="TOKEN",
        telegram_chat_id=None,
        redis_url=None,
        groq_api_key=None, gemini_api_key=None,
        deepseek_api_key=None, openrouter_api_key=None,
    )
    ledger = Ledger(str(tmp_path / "ledger.db"))
    with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID"):
        TelegramBridge(cfg, ledger)
