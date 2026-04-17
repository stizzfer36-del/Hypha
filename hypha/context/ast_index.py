"""M2 — tree-sitter AST index.

Role: parse every source file in the repo; emit a symbol graph
(file, symbol name, kind, span) into DuckDB. Re-run on file change.
Produces: `ast_symbols(path, name, kind, start_line, end_line)` in the
joint-query store.
Consumes: the repo's working tree.

Scope note: M2 indexes Python sources only. Other languages land when their
agents are needed.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import tree_sitter_python
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tree_sitter_python.language())

# Symbol-producing node kinds we care about.
SYMBOL_KINDS = {
    "function_definition": "function",
    "class_definition": "class",
    "assignment": "assignment",  # top-level constants; filtered by scope below
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ast_symbols (
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ast_symbols_name ON ast_symbols(name);
CREATE INDEX IF NOT EXISTS idx_ast_symbols_path ON ast_symbols(path);
"""


def _walk(node, src: bytes, out: list[tuple[str, str, int, int]]) -> None:
    kind = SYMBOL_KINDS.get(node.type)
    if kind in ("function", "class"):
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            name = src[name_node.start_byte : name_node.end_byte].decode(
                "utf-8", errors="replace"
            )
            out.append((name, kind, node.start_point[0] + 1, node.end_point[0] + 1))
    for child in node.children:
        _walk(child, src, out)


class ASTIndex:
    def __init__(self, repo_root: Path, duckdb_path: Path):
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.duckdb_path = Path(duckdb_path).expanduser().resolve()
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)

    def rebuild(self) -> int:
        parser = Parser(PY_LANGUAGE)
        con = duckdb.connect(str(self.duckdb_path))
        try:
            con.execute(SCHEMA)
            con.execute("DELETE FROM ast_symbols")
            rows: list[tuple[str, str, str, int, int]] = []
            for path in self.repo_root.rglob("*.py"):
                if ".venv" in path.parts or ".git" in path.parts:
                    continue
                rel = path.relative_to(self.repo_root).as_posix()
                try:
                    src = path.read_bytes()
                except OSError:
                    continue
                tree = parser.parse(src)
                symbols: list[tuple[str, str, int, int]] = []
                _walk(tree.root_node, src, symbols)
                for name, kind, a, b in symbols:
                    rows.append((rel, name, kind, a, b))
            if rows:
                con.executemany(
                    "INSERT INTO ast_symbols VALUES (?, ?, ?, ?, ?)", rows
                )
            return len(rows)
        finally:
            con.close()
