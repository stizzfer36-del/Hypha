"""Typer CLI surface.

Role: the human's primary read/write view over the ledger. Parity with the
Telegram bridge (commands and semantics).
Produces: `IntentCreated`, `DecisionRecorded`.
Consumes: ledger reads.
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


def _actor() -> str:
    return f"cli:{getpass.getuser()}"


@app.command()
def intent(text: str) -> None:
    """Record a new intent in the ledger."""

    async def _run() -> None:
        ledger = _ledger()
        await ledger.init()
        payload = json.dumps({"text": text})
        eid = await ledger.append(Kind.INTENT_CREATED, _actor(), payload)
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
            typer.echo(
                f"{e.ts:.0f} [{age:>5.0f}s] {e.kind:<18} {e.actor:<24} {e.payload}"
            )

    asyncio.run(_run())


@app.command()
def status() -> None:
    """Print what Hypha is currently doing."""

    async def _run() -> None:
        cfg = load_config()
        report = await render_status(str(cfg.db_path))
        typer.echo(report)

    asyncio.run(_run())


async def _decide(prefix: str, accepted: bool) -> None:
    ledger = _ledger()
    await ledger.init()
    rows = await ledger.recent(kind=Kind.VERIFICATION_PASSED, limit=200)
    match = next((r for r in rows if r.id.startswith(prefix)), None)
    if match is None:
        typer.echo(f"no VerificationPassed event matches prefix {prefix!r}")
        raise typer.Exit(code=1)
    payload = json.dumps({"accepted": accepted, "source": "cli"})
    eid = await ledger.append(
        Kind.DECISION_RECORDED, _actor(), payload, parent_id=match.id
    )
    typer.echo(
        f"{eid}  -- {'accepted' if accepted else 'rejected'} {match.id[:8]}"
    )


@app.command()
def accept(event_id_prefix: str) -> None:
    """Accept a VerificationPassed event by id prefix (8 chars is enough)."""
    asyncio.run(_decide(event_id_prefix, accepted=True))


@app.command()
def reject(event_id_prefix: str) -> None:
    """Reject a VerificationPassed event by id prefix."""
    asyncio.run(_decide(event_id_prefix, accepted=False))


@app.command()
def daemon() -> None:
    """Run the supervisor daemon in the foreground."""
    from hypha.daemon import run as _run

    _run()


@app.command()
def telegram() -> None:
    """Run the Telegram bridge in the foreground (requires bot token + chat id)."""
    from hypha.telegram_bridge import run as _run

    cfg = load_config()

    async def _main() -> None:
        ledger = Ledger(cfg.db_path)
        await ledger.init()
        await _run(cfg, ledger)

    asyncio.run(_main())


if __name__ == "__main__":
    app()
