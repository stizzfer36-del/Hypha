"""M1 — typer CLI surface.

Role: the human's primary read/write view over the ledger until Telegram
lands. Thin — every command is a one-liner over `Ledger`.
Produces: `IntentCreated` (via `hypha intent "..."`).
Consumes: ledger reads (`hypha events`, `hypha status`).
"""

from __future__ import annotations

import asyncio
import getpass
import json
import time

import typer

from hypha.config import load as load_config
from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.surface.status import render_status

app = typer.Typer(no_args_is_help=True, help="Hypha — talk to your repo.")


def _ledger() -> Ledger:
    cfg = load_config()
    return Ledger(cfg.db_path)


@app.command()
def intent(text: str) -> None:
    """Record a new intent in the ledger."""

    async def _run() -> None:
        ledger = _ledger()
        await ledger.init()
        payload = json.dumps({"text": text})
        actor = f"cli:{getpass.getuser()}"
        eid = await ledger.append(Kind.INTENT_CREATED, actor, payload)
        typer.echo(f"{eid}")

    asyncio.run(_run())


@app.command()
def events(limit: int = 20, kind: str = "") -> None:
    """Print recent ledger events, newest first."""

    async def _run() -> None:
        ledger = _ledger()
        await ledger.init()
        rows = await ledger.recent(kind=kind or None, limit=limit)
        now = time.time()
        for e in rows:
            age = now - e.ts
            typer.echo(f"{e.ts:.0f} [{age:>5.0f}s] {e.kind:<18} {e.actor:<24} {e.payload}")

    asyncio.run(_run())


@app.command()
def status() -> None:
    """Print what Hypha is currently doing."""

    async def _run() -> None:
        cfg = load_config()
        report = await render_status(str(cfg.db_path))
        typer.echo(report)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
