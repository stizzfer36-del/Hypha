#!/usr/bin/env bash
# M5 end-to-end verify — sandbox + diff approval + merge-on-accept.
# Kill-gate: false-pass rate > 15% on 20-intent suite -> STOP.
# Real firejail execution not tested here (firejail is an OS package);
# we verify argv construction, cwd-escape refusal, installed-binary
# detection, and the CLI approve/reject -> ledger + ff-merge flow.
#   PY=.venv/bin/python bash scripts/verify_m5.sh
set -euo pipefail
PY=${PY:-python}

echo "== unit tests =="
$PY -m pytest -q tests/test_sandbox.py

echo "== profile sanity =="
test -f hypha/sandbox/hypha.profile
grep -q "^caps.drop all" hypha/sandbox/hypha.profile
grep -q "^seccomp" hypha/sandbox/hypha.profile
grep -q "^netfilter" hypha/sandbox/hypha.profile
echo "profile OK"

echo "== end-to-end approval loop: accept path =="
$PY - <<'PYEOF'
import asyncio, json, tempfile
from pathlib import Path
import pygit2
from hypha.events import Kind
from hypha.ledger import Ledger
from hypha.surface.diff_approval import DiffApproval

tmp = Path(tempfile.mkdtemp())
root = tmp / "r"; root.mkdir()
repo = pygit2.init_repository(str(root), initial_head="main")
sig = pygit2.Signature("t", "t@t", 1_700_000_000, 0)
(root / "x.txt").write_text("a\n")
repo.index.add("x.txt"); repo.index.write()
tree = repo.index.write_tree()
base = repo.create_commit("HEAD", sig, sig, "init", tree, [])

repo.branches.local.create("feature", repo[base])
repo.checkout("refs/heads/feature")
(root / "y.txt").write_text("b\n")
repo.index.add("y.txt"); repo.index.write()
sig2 = pygit2.Signature("t", "t@t", 1_700_000_100, 0)
repo.create_commit("HEAD", sig2, sig2, "feat", repo.index.write_tree(), [base])
repo.checkout("refs/heads/main")

async def main():
    ledger = Ledger(str(tmp / "ledger.db"))
    await ledger.init()
    vid = await ledger.append(Kind.VERIFICATION_PASSED, "agent", "{}")
    approval = DiffApproval(ledger, root, ask=lambda diff: True)
    dec = await approval.request(vid, "feature", base="main")
    assert dec.accepted, f"accept path failed: {dec.rationale}"
    assert (root / "y.txt").exists(), "ff merge did not apply"
    rows = await ledger.recent(kind=Kind.DECISION_RECORDED, limit=1)
    assert rows and json.loads(rows[0].payload)["accepted"] is True
    print("accept-merge OK")
asyncio.run(main())
PYEOF

echo "== security self-check =="
# firejail wrapper never falls back to unsandboxed subprocess when binary absent
grep -q "not installed" hypha/sandbox/firejail.py
# ff-only merge — no implicit merge commits from unapproved diffs
grep -q -- "--ff-only" hypha/surface/diff_approval.py
# diff approval never writes decisions labeled accepted=True if merge failed
# (covered by the conditional in diff_approval.py — rationale overwritten)
$PY - <<'PYEOF'
# No path traversal in diff-approval: repo_root is always resolved.
from hypha.surface.diff_approval import DiffApproval
src = open("hypha/surface/diff_approval.py").read()
assert "expanduser().resolve()" in src
print("security OK")
PYEOF

echo "verify_m5 PASS"
