"""M7 — task claim with optimistic lock.

Role: claim-before-act over a SQLite-backed claim table. If two devices
claim the same task, one wins and the other sees conflict and backs off.
Conflict never results in silent merge; it raises to the human.
Produces: `TaskClaimed`, `TaskReleased`.
Consumes: tasks from the event bus.

Schema is a separate DB from the main ledger so multi-device synchronization
can live in a shared store (e.g. a network mount or a small replicated file)
without dragging the full event log along.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from hypha.events import Kind
from hypha.ledger import Ledger


SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    task_id     TEXT PRIMARY KEY,
    device_id   TEXT NOT NULL,
    claimed_ts  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_device ON claims(device_id);

CREATE TABLE IF NOT EXISTS heartbeats (
    device_id   TEXT PRIMARY KEY,
    last_seen_ts REAL NOT NULL,
    tags        TEXT NOT NULL
);
"""


@dataclass
class ClaimInfo:
    task_id: str
    device_id: str
    claimed_ts: float


class Claim:
    def __init__(self, path: str | Path, ledger: Optional[Ledger] = None):
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(resolved)
        self.ledger = ledger
        with sqlite3.connect(self.path) as db:
            db.executescript(SCHEMA)

    async def try_claim(self, task_id: str, device_id: str) -> bool:
        """Atomically claim a task. True = we own it; False = someone else
        holds it. Never silently overwrites an existing claim."""
        ts = time.time()
        with sqlite3.connect(self.path) as db:
            db.isolation_level = None  # manual txn
            db.execute("BEGIN IMMEDIATE")
            try:
                try:
                    db.execute(
                        "INSERT INTO claims (task_id, device_id, claimed_ts) "
                        "VALUES (?, ?, ?)",
                        (task_id, device_id, ts),
                    )
                    db.execute("COMMIT")
                except sqlite3.IntegrityError:
                    db.execute("ROLLBACK")
                    return False
            except Exception:
                db.execute("ROLLBACK")
                raise
        if self.ledger is not None:
            await self.ledger.append(
                Kind.TASK_CLAIMED,
                f"device:{device_id}",
                json.dumps({"task_id": task_id}),
            )
        return True

    async def release(self, task_id: str, device_id: str) -> bool:
        """Release a task. Returns True if we owned it; False if not.
        Only the current owner can release — prevents a rogue device from
        stealing a claim via release-then-claim."""
        with sqlite3.connect(self.path) as db:
            cur = db.execute(
                "DELETE FROM claims WHERE task_id = ? AND device_id = ?",
                (task_id, device_id),
            )
            released = cur.rowcount > 0
        if released and self.ledger is not None:
            await self.ledger.append(
                Kind.TASK_RELEASED,
                f"device:{device_id}",
                json.dumps({"task_id": task_id}),
            )
        return released

    def owner(self, task_id: str) -> Optional[ClaimInfo]:
        with sqlite3.connect(self.path) as db:
            cur = db.execute(
                "SELECT task_id, device_id, claimed_ts FROM claims WHERE task_id = ?",
                (task_id,),
            )
            row = cur.fetchone()
        return ClaimInfo(*row) if row else None

    async def release_stale(self, heartbeat_timeout_s: float) -> list[str]:
        """Release any claim whose device has not heartbeat'd within the
        timeout. Returns the list of released task_ids. The human is
        notified via TaskReleased events so a conflict can be investigated
        rather than silently healed."""
        cutoff = time.time() - heartbeat_timeout_s
        with sqlite3.connect(self.path) as db:
            cur = db.execute(
                "SELECT c.task_id, c.device_id FROM claims c "
                "LEFT JOIN heartbeats h ON h.device_id = c.device_id "
                "WHERE h.last_seen_ts IS NULL OR h.last_seen_ts < ?",
                (cutoff,),
            )
            stale = cur.fetchall()
            for task_id, _ in stale:
                db.execute("DELETE FROM claims WHERE task_id = ?", (task_id,))
        released: list[str] = []
        for task_id, device_id in stale:
            if self.ledger is not None:
                await self.ledger.append(
                    Kind.TASK_RELEASED,
                    f"supervisor:stale",
                    json.dumps(
                        {"task_id": task_id, "former_device": device_id, "reason": "stale"}
                    ),
                )
            released.append(task_id)
        return released
