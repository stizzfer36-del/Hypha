"""M1 (optional) — Telegram surface.

Role: second intent input channel. Each incoming message becomes an
`IntentCreated` event; each `DecisionRecorded` or approval-requested event
surfaces back to the user as a message or inline-button prompt.
Produces: `IntentCreated`, approval responses.
Consumes: `DecisionRecorded`, `PatchSubmitted` (for approval surfaces).

Deferred in the default M1 build (user has no bot token). Left as a stub so
wiring later is env-var-only, no code reshuffle.
"""

from __future__ import annotations


async def run() -> None:
    raise NotImplementedError(
        "Telegram bridge: poll python-telegram-bot, route to ledger"
    )
