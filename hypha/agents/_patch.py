"""Shared helpers for agents that produce file-write patches.

Every Hypha agent that edits code speaks the same JSON shape:
    {"files": {"rel/path.py": "full file contents", ...}}
This module centralizes parse + apply so the fused agent and the split
planner/coder variants can't drift in how they validate paths.
"""

from __future__ import annotations

import json
from pathlib import Path


class PatchFormatError(ValueError):
    pass


def parse_patch(text: str) -> dict[str, str]:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise PatchFormatError(f"response is not valid JSON: {e}") from e
    if not isinstance(obj, dict) or "files" not in obj or not isinstance(
        obj["files"], dict
    ):
        raise PatchFormatError('response must be {"files": {...}}')
    files = obj["files"]
    for k, v in files.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise PatchFormatError("each file entry must be str->str")
        if k.startswith("/") or ".." in Path(k).parts:
            raise PatchFormatError(f"unsafe path: {k}")
    return files


def apply_patch(root: Path, files: dict[str, str]) -> list[str]:
    root = Path(root).resolve()
    written: list[str] = []
    for rel, body in files.items():
        dest = (root / rel).resolve()
        if (
            not str(dest).startswith(str(root) + "/")
            and dest != root
        ):
            raise PatchFormatError(f"patch escapes worktree: {rel}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body)
        written.append(rel)
    return written
