"""M1 — append-only SQLite event ledger.

Role: single source of truth. Every component reads and writes events here.
Produces: nothing directly — callers write events they own.
Consumes: nothing — this module IS the log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Event:
    id: str
    ts: float
    kind: str
    actor: str
    payload: str
    parent_id: Optional[str] = None


class Ledger:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        raise NotImplementedError("M1: create schema + indexes, enable WAL")

    async def append(
        self,
        kind: str,
        actor: str,
        payload: str,
        parent_id: Optional[str] = None,
    ) -> str:
        raise NotImplementedError("M1: insert row, return new event id")

    async def recent(
        self, kind: Optional[str] = None, limit: int = 50
    ) -> list[Event]:
        raise NotImplementedError("M1: read latest rows, optional kind filter")
