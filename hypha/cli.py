"""M1 — typer CLI surface.

Role: the human's primary read/write view over the ledger until Telegram
lands. Thin — every command is a one-liner over `Ledger`.
Produces: `IntentCreated` (via `hypha intent "..."`).
Consumes: ledger reads (`hypha events`, `hypha status`).
"""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, help="Hypha — talk to your repo.")


@app.command()
def intent(text: str) -> None:
    """Record a new intent in the ledger."""
    raise NotImplementedError("M1: append IntentCreated with actor=cli:<user>")


@app.command()
def events(limit: int = 20, kind: str = "") -> None:
    """Print recent ledger events."""
    raise NotImplementedError("M1: read ledger.recent, pretty-print")


@app.command()
def status() -> None:
    """Print what Hypha is currently doing."""
    raise NotImplementedError("M1: last N events + daemon liveness summary")


if __name__ == "__main__":
    app()
