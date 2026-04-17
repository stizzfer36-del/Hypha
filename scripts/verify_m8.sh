#!/usr/bin/env bash
# M8 end-to-end verify — four-layer context engine v2.
# Kill-gate: still context-starved on a real repo -> add tool-use-at-retrieval
# before declaring v2 shipped.
# This script exercises all four layers on a toy repo; the real-repo gate must
# be walked manually against a non-toy target.
#   PY=.venv/bin/python bash scripts/verify_m8.sh
set -euo pipefail
PY=${PY:-python}

echo "== unit tests (v1 compat + v2) =="
$PY -m pytest -q tests/test_context_joint_query.py tests/test_context_v2.py

echo "== end-to-end: four layers contribute signal =="
$PY - <<'PYEOF'
import tempfile, time
from pathlib import Path
import pygit2

from hypha.context.ast_index import ASTIndex
from hypha.context.git_history import GitHistory
from hypha.context.runtime_traces import RuntimeTraces
from hypha.context.embeddings import Embeddings, HashEncoder
from hypha.context.joint_query import JointQuery

tmp = Path(tempfile.mkdtemp())
root = tmp / "toy"; root.mkdir()
repo = pygit2.init_repository(str(root), initial_head="main")
sig = pygit2.Signature("t", "t@t", 1_700_000_000, 0)
(root / "auth.py").write_text("def authenticate(user):\n    return user\n\nclass AuthSession: pass\n")
(root / "billing.py").write_text("def charge(a):\n    return a\n\ndef invoice_for(c):\n    return c\n")
repo.index.add("auth.py"); repo.index.add("billing.py"); repo.index.write()
repo.create_commit("HEAD", sig, sig, "init", repo.index.write_tree(), [])
(root / "billing.py").write_text("def charge(a):\n    return a\n\ndef invoice_for(c):\n    return c * 2\n")
repo.index.add("billing.py"); repo.index.write()
repo.create_commit("HEAD", sig, sig, "tweak invoice flow", repo.index.write_tree(), [repo.head.target])

duck = tmp / "joint.duckdb"
ASTIndex(root, duck).rebuild()
GitHistory(root, duck).rebuild()
now = time.time()
RuntimeTraces(duck).ingest([
    {"path": "billing.py", "func": "invoice_for", "ts": now - 60, "ok": False},
    {"path": "billing.py", "func": "invoice_for", "ts": now - 30, "ok": False},
])
emb = Embeddings(duck, encoder=HashEncoder(dim=128))
emb.reset()
emb.upsert([
    ("file", "auth.py", "authenticate login session user"),
    ("file", "billing.py", "invoice charge payment billing"),
])

slices = JointQuery(duck, embeddings=emb).query("fix invoice charge", limit=3)
assert slices, "no results"
top = slices[0]
assert top.path == "billing.py", f"expected billing.py, got {top.path}"
r = top.rationale
# Each of four layers contributes:
assert r["ast_symbols"], "missing ast_symbols"
assert r["git_commits"], "missing git commit signal"
assert r["runtime"] and r["runtime"]["fails"] >= 2, "missing runtime signal"
assert r["embedding_sim"] is not None, "missing embedding signal"
print("four-layer rationale:", r)
print("OK four-layer")
PYEOF

echo "== security self-check =="
# Runtime traces redact secret-looking keys + token-looking values.
$PY - <<'PYEOF'
from hypha.context.runtime_traces import _redact
out = _redact({"api_key": "sk-abcdefghijklmnopqrstuvwxyz12", "nonce": "x"*40, "count": 3})
assert "redacted" in out["api_key"]
assert "redacted" in out["nonce"]
assert out["count"] == 3
print("redaction OK")
PYEOF

# Embedding index storage is local (duckdb path under repo); no network.
grep -q "duckdb.connect" hypha/context/embeddings.py
if grep -RE '\b(requests|httpx|urllib)\b' hypha/context/embeddings.py hypha/context/runtime_traces.py 2>/dev/null; then
  echo "FAIL: embeddings/runtime-traces reference a network lib"; exit 1
fi
echo "security OK"

echo "verify_m8 PASS"
echo
echo "NOTE: the 'context-starved on real repo' kill-gate must be walked by"
echo "running this against a non-toy repo. If slices fail to surface the"
echo "intent-relevant file consistently, add tool-use-at-retrieval (agents"
echo "run grep/read/tests) before declaring v2 shipped."
