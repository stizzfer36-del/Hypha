"""M8 — runtime trace capture.

Role: during pytest / dev runs, capture OpenTelemetry-style spans and link
them back to source spans. Trace data redacts secrets before storage.
Produces: `runtime_spans` table.
Consumes: test-run instrumentation hook.
"""

from __future__ import annotations

from pathlib import Path


class RuntimeTraces:
    def __init__(self, duckdb_path: Path):
        self.duckdb_path = duckdb_path

    def ingest(self, spans: list[dict]) -> int:
        raise NotImplementedError(
            "M8: redact env-var-looking values, upsert into runtime_spans"
        )
