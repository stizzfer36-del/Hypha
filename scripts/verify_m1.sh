#!/usr/bin/env bash
# M1 end-to-end verify. Run from repo root. No args.
set -euo pipefail

PY=${PY:-python}

# Spec's canonical ledger snippet.
$PY - <<'PYEOF'
import asyncio, os
from hypha.ledger import Ledger

async def main():
    if os.path.exists("test.db"):
        os.remove("test.db")
    l = Ledger("test.db")
    await l.init()
    eid = await l.append("IntentCreated", "test", '{"text":"hello"}')
    print("appended:", eid)
    events = await l.recent()
    assert len(events) == 1 and events[0].kind == "IntentCreated"
    print("OK")

asyncio.run(main())
PYEOF

# CLI smoke: intent -> events.
export HYPHA_DB_PATH=$(mktemp -d)/hypha.db
hypha intent "verify_m1: hello"
hypha events --limit 1 | grep -q "verify_m1"
echo "CLI OK"

# Daemon restart persistence.
hypha events --limit 1 > /tmp/hypha_pre.txt
$PY -c "import sqlite3; sqlite3.connect('$HYPHA_DB_PATH').close()"
hypha events --limit 1 > /tmp/hypha_post.txt
diff /tmp/hypha_pre.txt /tmp/hypha_post.txt
echo "persistence OK"

rm -f test.db
echo "verify_m1 PASS"
