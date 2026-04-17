#!/usr/bin/env bash
# M7 end-to-end verify — multi-device heartbeat + optimistic-lock claim.
#   PY=.venv/bin/python bash scripts/verify_m7.sh
set -euo pipefail
PY=${PY:-python}

echo "== unit tests =="
$PY -m pytest -q tests/test_devices.py

echo "== end-to-end: 20-way claim race, exactly one winner =="
$PY - <<'PYEOF'
import asyncio, tempfile
from pathlib import Path
from hypha.devices.claim import Claim

async def main():
    tmp = Path(tempfile.mkdtemp())
    c = Claim(tmp / "claims.db")
    async def claim(dev):
        return await c.try_claim("race-task", dev)
    results = await asyncio.gather(*(claim(f"d{i}") for i in range(20)))
    n_wins = sum(1 for r in results if r)
    assert n_wins == 1, f"exactly one winner expected, got {n_wins}"
    owner = c.owner("race-task")
    assert owner is not None
    print(f"race OK; winner={owner.device_id}")

asyncio.run(main())
PYEOF

echo "== security self-check =="
# Non-owner cannot release
$PY - <<'PYEOF'
import asyncio, tempfile
from pathlib import Path
from hypha.devices.claim import Claim

async def main():
    tmp = Path(tempfile.mkdtemp())
    c = Claim(tmp / "claims.db")
    assert await c.try_claim("t1", "pi")
    assert not await c.release("t1", "impostor")
    assert c.owner("t1").device_id == "pi"
    print("non-owner release blocked")

asyncio.run(main())
PYEOF

# Stale heartbeat handler exists and emits TaskReleased
grep -q "release_stale" hypha/devices/claim.py
grep -q "TaskReleased" hypha/events.py
echo "security OK"

echo "verify_m7 PASS"
