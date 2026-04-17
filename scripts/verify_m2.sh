#!/usr/bin/env bash
# M2 end-to-end verify — context engine v1 on a toy repo.
#   PY=.venv/bin/python bash scripts/verify_m2.sh
set -euo pipefail

PY=${PY:-python}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "== unit tests =="
$PY -m pytest -q tests/test_context_joint_query.py

echo "== end-to-end: natural-language query returns ranked slices with rationale =="
$PY - "$TMP" <<'PYEOF'
import json, sys, time
from pathlib import Path

import pygit2

from hypha.context.ast_index import ASTIndex
from hypha.context.git_history import GitHistory
from hypha.context.joint_query import JointQuery

tmp = Path(sys.argv[1])
repo_dir = tmp / "toy"
repo_dir.mkdir()
repo = pygit2.init_repository(str(repo_dir), initial_head="main")
sig = pygit2.Signature("t", "t@t", 1_700_000_000, 0)

def commit(files, msg):
    for rel, body in files.items():
        (repo_dir / rel).write_text(body)
        repo.index.add(rel)
    repo.index.write()
    tree = repo.index.write_tree()
    parents = [] if repo.head_is_unborn else [repo.head.target]
    return str(repo.create_commit("HEAD", sig, sig, msg, tree, parents))

commit(
    {
        "auth.py": "def authenticate(u):\n    return u\n\nclass AuthSession: pass\n",
        "billing.py": "def charge(a):\n    return a\n\nclass Invoice: pass\n",
    },
    "add auth and billing",
)
commit(
    {
        "auth.py": "def authenticate(u):\n    return u\n\ndef authorize(u,s):\n    return True\n\nclass AuthSession: pass\n"
    },
    "add authorize to auth flow",
)

duck = tmp / "joint.duckdb"
ASTIndex(repo_dir, duck).rebuild()
GitHistory(repo_dir, duck).rebuild()

t0 = time.perf_counter()
slices = JointQuery(duck).query("make auth idempotent", limit=5)
ms = (time.perf_counter() - t0) * 1000

assert slices, "no slices returned"
top = slices[0]
assert top.path == "auth.py", f"expected auth.py, got {top.path}"
assert top.score > 0
assert top.rationale["ast_symbols"], "rationale missing ast_symbols"
assert any(s.lower().startswith("auth") for s in top.rationale["ast_symbols"])

print(f"top slice: {top.path}:{top.start_line}-{top.end_line} score={top.score}")
print(f"rationale: {json.dumps(top.rationale, sort_keys=True)}")
print(f"query_ms: {ms:.1f}")
assert ms < 2000, f"query took {ms:.1f}ms; target <2000ms"
print("OK")
PYEOF

echo "== security self-check =="
# tree-sitter parsing is pure parsing; no eval in our code
if grep -RE '\b(eval|exec)\s*\(' hypha/context/ ; then
  echo "FAIL: eval/exec in context layer"; exit 1
fi
# git traversal is confined to self.repo_root (no submodule fetches, no remote calls)
if grep -RE 'pygit2\.(clone|discover_repository)\b' hypha/context/ ; then
  echo "FAIL: unexpected repo discovery/clone"; exit 1
fi
echo "security OK"

echo "verify_m2 PASS"
