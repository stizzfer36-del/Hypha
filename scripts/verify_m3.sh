#!/usr/bin/env bash
# M3 end-to-end verify — plan-code-verify loop on worktree branch, pytest gate.
# Uses a scripted FakeRouter so no live model credentials are required.
#   PY=.venv/bin/python bash scripts/verify_m3.sh
set -euo pipefail
PY=${PY:-python}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "== unit tests =="
$PY -m pytest -q tests/test_loop.py

echo "== end-to-end: real intent -> worktree -> pytest pass =="
$PY - "$TMP" <<'PYEOF'
import asyncio, json, sys
from dataclasses import dataclass
from pathlib import Path

import pygit2
from hypha.agents.fused import FusedAgent
from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.router import Request, Response

tmp = Path(sys.argv[1])
root = tmp / "toy"
root.mkdir()
repo = pygit2.init_repository(str(root), initial_head="main")
sig = pygit2.Signature("t", "t@t", 1_700_000_000, 0)
(root / "tests").mkdir()
(root / "tests" / "test_it.py").write_text(
    "from mymod import answer\n\ndef test_answer():\n    assert answer() == 42\n"
)
(root / "conftest.py").write_text(
    "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent))\n"
)
repo.index.add("tests/test_it.py"); repo.index.add("conftest.py")
repo.index.write()
tree = repo.index.write_tree()
repo.create_commit("HEAD", sig, sig, "init", tree, [])

@dataclass
class FR:
    text: str
    async def call(self, req: Request) -> Response:
        return Response(text=self.text, provider="fake", model="m", tokens_in=0, tokens_out=0, ms=0)

async def main():
    ledger = Ledger(str(tmp / "ledger.db"))
    await ledger.init()
    eid = await ledger.append(Kind.INTENT_CREATED, "cli:t", json.dumps({"text": "make answer=42"}))
    good = json.dumps({"files": {"mymod.py": "def answer():\n    return 42\n"}})
    res = await FusedAgent(ledger, FR(text=good), root).handle(eid)
    assert res.ok, f"expected pass, got failure; branch={res.branch}"
    kinds = [r.kind for r in await ledger.recent(limit=10)]
    for required in ("IntentCreated", "PlanProposed", "PatchSubmitted", "VerificationPassed"):
        assert required in kinds, f"missing event: {required}; saw {kinds}"
    print("OK end-to-end pass")

asyncio.run(main())
PYEOF

echo "== security self-check =="
# patch paths with traversal or abs path must be rejected at _parse_patch.
# Confirmed via tests/test_loop.py::test_loop_rejects_path_traversal.
# Extra static checks:
if grep -RE 'os\.environ' hypha/agents/ hypha/router.py 2>/dev/null; then
  echo "FAIL: env vars referenced in agent/router — review for leakage"; exit 1
fi
if grep -RE '\bshell=True\b' hypha/ 2>/dev/null; then
  echo "FAIL: subprocess shell=True in hypha/"; exit 1
fi
echo "security OK"

echo "verify_m3 PASS"
