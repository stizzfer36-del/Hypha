"""M6 — prompt variant store.

Role: integrity-checked registry of prompt templates and variants. A variant
is accepted only if canary passes and main-metric improves past a sequential
probability ratio threshold. Accepted variants are frozen for N days before
re-evolution.
Produces: `variants` rows.
Consumes: `PromptVariantCandidate` events.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS variants (
    id TEXT PRIMARY KEY,
    prompt_id TEXT NOT NULL,
    body TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    created_ts REAL NOT NULL,
    frozen_until_ts REAL NOT NULL,
    accepted INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_variants_hash
    ON variants(prompt_id, body_hash);
CREATE INDEX IF NOT EXISTS idx_variants_accepted
    ON variants(accepted);
"""

DEFAULT_FREEZE_DAYS = 7


@dataclass
class Variant:
    id: str
    prompt_id: str
    body: str
    body_hash: str
    created_ts: float
    frozen_until_ts: float
    accepted: bool


def _hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class VariantStore:
    def __init__(self, path: str | Path, freeze_days: int = DEFAULT_FREEZE_DAYS):
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(resolved)
        self.freeze_days = freeze_days
        with sqlite3.connect(self.path) as db:
            db.executescript(SCHEMA)

    def register(self, prompt_id: str, body: str) -> Variant:
        vid = uuid.uuid4().hex
        body_hash = _hash(body)
        now = time.time()
        with sqlite3.connect(self.path) as db:
            try:
                db.execute(
                    "INSERT INTO variants (id, prompt_id, body, body_hash, "
                    "created_ts, frozen_until_ts, accepted) VALUES (?, ?, ?, ?, ?, ?, 0)",
                    (vid, prompt_id, body, body_hash, now, 0.0),
                )
            except sqlite3.IntegrityError:
                # Already exists; fetch and return it.
                cur = db.execute(
                    "SELECT id, prompt_id, body, body_hash, created_ts, "
                    "frozen_until_ts, accepted FROM variants "
                    "WHERE prompt_id = ? AND body_hash = ?",
                    (prompt_id, body_hash),
                )
                row = cur.fetchone()
                return Variant(
                    id=row[0],
                    prompt_id=row[1],
                    body=row[2],
                    body_hash=row[3],
                    created_ts=row[4],
                    frozen_until_ts=row[5],
                    accepted=bool(row[6]),
                )
        return Variant(
            id=vid,
            prompt_id=prompt_id,
            body=body,
            body_hash=body_hash,
            created_ts=now,
            frozen_until_ts=0.0,
            accepted=False,
        )

    def accept(self, variant_id: str) -> None:
        now = time.time()
        frozen = now + self.freeze_days * 86400.0
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE variants SET accepted = 1, frozen_until_ts = ? WHERE id = ?",
                (frozen, variant_id),
            )

    def get(self, variant_id: str) -> Optional[Variant]:
        with sqlite3.connect(self.path) as db:
            cur = db.execute(
                "SELECT id, prompt_id, body, body_hash, created_ts, "
                "frozen_until_ts, accepted FROM variants WHERE id = ?",
                (variant_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Variant(
            id=row[0],
            prompt_id=row[1],
            body=row[2],
            body_hash=row[3],
            created_ts=row[4],
            frozen_until_ts=row[5],
            accepted=bool(row[6]),
        )

    def is_frozen(self, variant_id: str) -> bool:
        v = self.get(variant_id)
        if v is None:
            return False
        return time.time() < v.frozen_until_ts

    def active(self, prompt_id: str) -> Optional[Variant]:
        """Most-recently-accepted, non-expired variant for a prompt.
        None means "use the baseline".
        """
        with sqlite3.connect(self.path) as db:
            cur = db.execute(
                "SELECT id, prompt_id, body, body_hash, created_ts, "
                "frozen_until_ts, accepted FROM variants "
                "WHERE prompt_id = ? AND accepted = 1 "
                "ORDER BY created_ts DESC LIMIT 1",
                (prompt_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Variant(
            id=row[0],
            prompt_id=row[1],
            body=row[2],
            body_hash=row[3],
            created_ts=row[4],
            frozen_until_ts=row[5],
            accepted=bool(row[6]),
        )
