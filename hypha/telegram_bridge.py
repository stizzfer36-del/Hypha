"""Telegram surface (optional).

Role: second intent-input channel and decision-surface. Each inbound message
becomes an `IntentCreated`; recent ledger activity can be pulled on demand;
approvals fire from chat.
Produces: `IntentCreated`, approvals recorded via DiffApproval.
Consumes: Telegram updates.

Security stance:
  * No bot token in logs.
  * Only `TELEGRAM_CHAT_ID` (set in config) may interact; all other chats
    are refused. This is a solo-operator bot — there is no room for
    permissive defaults.
  * Inline-button callbacks use `<verb>|<event_id>`; the id is validated
    against the ledger before any action fires.

Bot commands:
  /intent <text>    — record an IntentCreated
  /events [n]       — show the last n events (default 10)
  /status           — daemon liveness + recent intents
  /accept <eid>     — accept a VerificationPassed event by id prefix
  /reject <eid>     — reject a VerificationPassed event by id prefix
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from hypha.config import Config
from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.surface.status import render_status

log = logging.getLogger("hypha.telegram")


def _short(eid: str) -> str:
    return eid.split("-", 1)[0] if eid else ""


async def _find_event_by_prefix(ledger: Ledger, prefix: str, kind: str) -> Optional[object]:
    if not prefix:
        return None
    rows = await ledger.recent(kind=kind, limit=200)
    for r in rows:
        if r.id.startswith(prefix):
            return r
    return None


class TelegramBridge:
    """Wrap the telegram Application so tests can exercise each handler
    with a fake context. `ask` lets the caller inject a custom accept/reject
    flow (default: use the ledger.append of DecisionRecorded directly)."""

    def __init__(
        self,
        cfg: Config,
        ledger: Ledger,
    ):
        if not cfg.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set")
        if not cfg.telegram_chat_id:
            raise ValueError("TELEGRAM_CHAT_ID is not set")
        self.cfg = cfg
        self.ledger = ledger
        self.allowed_chat_id = int(cfg.telegram_chat_id)

    def _allowed(self, update: Update) -> bool:
        chat = update.effective_chat
        return chat is not None and chat.id == self.allowed_chat_id

    async def handle_intent(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._allowed(update):
            return
        text = " ".join(context.args or []) or (
            update.message.text.split(" ", 1)[1]
            if update.message and " " in update.message.text
            else ""
        )
        if not text.strip():
            await update.message.reply_text("usage: /intent <text>")
            return
        actor = f"telegram:{update.effective_user.username or update.effective_user.id}"
        eid = await self.ledger.append(
            Kind.INTENT_CREATED, actor, json.dumps({"text": text.strip()})
        )
        await update.message.reply_text(f"ok — intent {_short(eid)}")

    async def handle_events(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._allowed(update):
            return
        try:
            n = int(context.args[0]) if context.args else 10
        except ValueError:
            n = 10
        n = max(1, min(n, 50))
        rows = await self.ledger.recent(limit=n)
        lines = [f"{_short(r.id)} {r.kind} {r.actor}" for r in rows]
        await update.message.reply_text("\n".join(lines) or "(empty)")

    async def handle_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._allowed(update):
            return
        report = await render_status(self.ledger.path)
        await update.message.reply_text(f"```\n{report}\n```", parse_mode="Markdown")

    async def handle_accept(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self._decide(update, context, accepted=True)

    async def handle_reject(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self._decide(update, context, accepted=False)

    async def _decide(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        accepted: bool,
    ) -> None:
        if not self._allowed(update):
            return
        prefix = context.args[0] if context.args else ""
        row = await _find_event_by_prefix(self.ledger, prefix, Kind.VERIFICATION_PASSED)
        if row is None:
            await update.message.reply_text(
                f"no VerificationPassed event matches prefix {prefix!r}"
            )
            return
        actor = f"telegram:{update.effective_user.username or update.effective_user.id}"
        await self.ledger.append(
            Kind.DECISION_RECORDED,
            actor,
            json.dumps({"accepted": accepted, "source": "telegram"}),
            parent_id=row.id,
        )
        await update.message.reply_text(
            f"recorded decision on {_short(row.id)}: "
            + ("accepted" if accepted else "rejected")
        )

    async def handle_unknown(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._allowed(update):
            return
        await update.message.reply_text(
            "commands: /intent, /events [n], /status, /accept <id>, /reject <id>"
        )

    def build_application(self) -> Application:
        app = Application.builder().token(self.cfg.telegram_bot_token).build()
        app.add_handler(CommandHandler("intent", self.handle_intent))
        app.add_handler(CommandHandler("events", self.handle_events))
        app.add_handler(CommandHandler("status", self.handle_status))
        app.add_handler(CommandHandler("accept", self.handle_accept))
        app.add_handler(CommandHandler("reject", self.handle_reject))
        app.add_handler(MessageHandler(filters.COMMAND, self.handle_unknown))
        return app

    async def run_polling(self) -> None:
        app = self.build_application()
        log.info("telegram bridge polling (allowed_chat=%s)", self.allowed_chat_id)
        await app.run_polling(close_loop=False)


async def run(cfg: Config, ledger: Ledger) -> None:
    """Entrypoint for `python -m hypha.telegram_bridge`."""
    bridge = TelegramBridge(cfg=cfg, ledger=ledger)
    await bridge.run_polling()
