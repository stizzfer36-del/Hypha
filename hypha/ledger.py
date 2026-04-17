"""M1 — append-only SQLite event ledger.

Role: single source of truth. Every component reads and writes events here.
Produces: nothing directly — callers write events they own.
Consumes: nothing — this module IS the log.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload TEXT NOT NULL,
    parent_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


@dataclass
class Event:
    id: str
    ts: float
    kind: str
    actor: str
    payload: str
    parent_id: Optional[str] = None


class Ledger:
    def __init__(self, path: str | Path):
        resolved = Path(path).expanduser().resolve()
        if resolved.is_dir():
            raise ValueError(f"ledger path is a directory: {resolved}")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(resolved)

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.executescript(SCHEMA)
            await db.commit()

    async def append(
        self,
        kind: str,
        actor: str,
        payload: str,
        parent_id: Optional[str] = None,
    ) -> str:
        event_id = str(uuid.uuid4())
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO events (id, ts, kind, actor, payload, parent_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, time.time(), kind, actor, payload, parent_id),
            )
            await db.commit()
        return event_id

    async def recent(
        self, kind: Optional[str] = None, limit: int = 50
    ) -> list[Event]:
        query = "SELECT id, ts, kind, actor, payload, parent_id FROM events"
        params: tuple = ()
        if kind:
            query += " WHERE kind = ?"
            params = (kind,)
        query += " ORDER BY ts DESC LIMIT ?"
        params = params + (limit,)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [Event(*row) for row in rows]
