#!/usr/bin/env bash
# M1 end-to-end verify. Run from repo root with the venv active, or via:
#   PY=.venv/bin/python HYPHA=.venv/bin/hypha bash scripts/verify_m1.sh
set -euo pipefail

PY=${PY:-python}
HYPHA=${HYPHA:-hypha}

TMP=$(mktemp -d)
export HYPHA_DB_PATH="$TMP/hypha.db"
trap 'rm -rf "$TMP"' EXIT

echo "== ledger canonical snippet =="
$PY - <<'PYEOF'
import asyncio, os, json
from hypha.ledger import Ledger

async def main():
    path = os.environ["HYPHA_DB_PATH"]
    l = Ledger(path)
    await l.init()
    eid = await l.append("IntentCreated", "test", json.dumps({"text": "hello"}))
    print("appended:", eid)
    events = await l.recent()
    assert len(events) == 1 and events[0].kind == "IntentCreated"
    print("OK")

asyncio.run(main())
PYEOF

echo "== CLI intent + events =="
$HYPHA intent "verify_m1: hello"
$HYPHA events --limit 5 | grep -q "verify_m1: hello"
echo "CLI OK"

echo "== daemon lifecycle =="
$PY -m hypha.daemon > "$TMP/daemon.out" 2>&1 &
DPID=$!
sleep 1
$HYPHA intent "from cli while daemon runs"
sleep 2
kill -TERM $DPID
wait $DPID 2>/dev/null || true
grep -q "DaemonStarted" "$TMP/daemon.out"
grep -q "IntentCreated" "$TMP/daemon.out"
$HYPHA events --limit 20 | grep -q "DaemonStarted"
$HYPHA events --limit 20 | grep -q "DaemonStopped"
echo "lifecycle OK"

echo "== persistence across reconnect =="
$HYPHA events --limit 1 > "$TMP/pre.txt"
$PY -c "import sqlite3; sqlite3.connect('$HYPHA_DB_PATH').close()"
$HYPHA events --limit 1 > "$TMP/post.txt"
diff "$TMP/pre.txt" "$TMP/post.txt"
echo "persistence OK"

echo "== security self-check =="
# .env is gitignored
git check-ignore .env > /dev/null || { echo "FAIL: .env not gitignored"; exit 1; }
# .env.example does not contain real secrets (empty values only)
if grep -E "^[A-Z_]+=[^ ]" .env.example | grep -Ev "=$|=\./" ; then
  echo "FAIL: .env.example has a non-empty value"
  exit 1
fi
# No unparameterized SQL in hypha/
if grep -RE 'execute\([^?]*["'\''][^"'\'']*%[sd]' hypha/ ; then
  echo "FAIL: unparameterized SQL"
  exit 1
fi
# DB path is always resolved — directory paths rejected
DIR_ERR=$($PY -c "from hypha.ledger import Ledger; Ledger('$TMP')" 2>&1 || true)
echo "$DIR_ERR" | grep -q "directory"
echo "directory-path check OK"
echo "security OK"

echo "verify_m1 PASS"
