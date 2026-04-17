"""M8 — runtime trace capture.

Role: during pytest / dev runs, capture spans and link them back to source
paths. Trace data redacts obvious secrets before storage.
Produces: `runtime_spans(path, func, ts, ok)` table.
Consumes: test-run instrumentation hook (external caller passes spans in).

Scope: we accept a list of dict spans shaped like
  {"path": "a/b.py", "func": "fn", "ts": float, "ok": bool, "attrs": {...}}
The actual test-instrumentation plugin (pytest fixture) lives outside this
module; this file is storage + redaction only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb


SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_spans (
    path TEXT NOT NULL,
    func TEXT NOT NULL,
    ts   DOUBLE NOT NULL,
    ok   BOOLEAN NOT NULL,
    attrs TEXT
);
CREATE INDEX IF NOT EXISTS idx_rs_path ON runtime_spans(path);
CREATE INDEX IF NOT EXISTS idx_rs_ok   ON runtime_spans(ok);
CREATE INDEX IF NOT EXISTS idx_rs_ts   ON runtime_spans(ts);
"""

# Redact anything whose key looks secret-ish, plus values that look like
# high-entropy tokens. Conservative rather than clever — if in doubt, drop.
_SECRET_KEY = re.compile(r"(?i)(token|key|secret|password|authorization|cookie)")
_TOKENISH = re.compile(r"^[A-Za-z0-9_\-]{24,}$")


def _redact(attrs: dict[str, Any] | None) -> dict[str, Any]:
    if not attrs:
        return {}
    out: dict[str, Any] = {}
    for k, v in attrs.items():
        if _SECRET_KEY.search(k):
            out[k] = "<redacted:key>"
            continue
        if isinstance(v, str) and _TOKENISH.match(v):
            out[k] = "<redacted:value>"
            continue
        out[k] = v
    return out


class RuntimeTraces:
    def __init__(self, duckdb_path: Path):
        self.duckdb_path = Path(duckdb_path).expanduser().resolve()
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(self.duckdb_path))
        try:
            con.execute(SCHEMA)
        finally:
            con.close()

    def ingest(self, spans: list[dict]) -> int:
        import json as _json

        con = duckdb.connect(str(self.duckdb_path))
        try:
            rows: list[tuple] = []
            for s in spans:
                rows.append(
                    (
                        str(s["path"]),
                        str(s.get("func", "")),
                        float(s["ts"]),
                        bool(s.get("ok", True)),
                        _json.dumps(_redact(s.get("attrs"))),
                    )
                )
            if rows:
                con.executemany(
                    "INSERT INTO runtime_spans (path, func, ts, ok, attrs) "
                    "VALUES (?, ?, ?, ?, ?)",
                    rows,
                )
            return len(rows)
        finally:
            con.close()
