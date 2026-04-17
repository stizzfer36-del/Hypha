#!/usr/bin/env bash
# M6 end-to-end verify — run-log + variants + canary + clustering.
# Kill-gate: canary pass rate not monotonic over 14 days -> STOP.
# Non-negotiable: canary guard must exist and reject regressions; reflection
# must not short-circuit the canary.
#   PY=.venv/bin/python bash scripts/verify_m6.sh
set -euo pipefail
PY=${PY:-python}

echo "== unit tests =="
$PY -m pytest -q tests/test_reflection.py

echo "== end-to-end: reflect -> canary rejects regression =="
$PY - <<'PYEOF'
import asyncio, tempfile
from pathlib import Path

from hypha.ledger import Ledger
from hypha.reflection.canary import CanaryGuard, CanaryTask
from hypha.reflection.clustering import Clusterer
from hypha.reflection.run_log import Run, RunLog
from hypha.reflection.variants import VariantStore

tmp = Path(tempfile.mkdtemp())
rl = RunLog(tmp / "runs.db")
for _ in range(5):
    rl.append(Run(agent="a", prompt_id="code", variant_id="v1",
                  model="m", tokens_in=0, tokens_out=0,
                  verification_passed=False, ms=1,
                  failure_signature="JSONDecodeError"))

vs = VariantStore(tmp / "variants.db")
tasks = [
    CanaryTask("a", "1+1", lambda o: o == "2"),
    CanaryTask("b", "hi",  lambda o: o == "hi"),
    CanaryTask("c", "21",  lambda o: o == "42"),
]
guard = CanaryGuard(tasks)

async def propose(prompt_id, rs):
    return "regressing variant"

async def main():
    ledger = Ledger(str(tmp / "ledger.db"))
    await ledger.init()
    clusters = await Clusterer(rl, ledger, propose).reflect_nightly()
    assert len(clusters) == 1

    async def bad_run(body, inp):
        return {"1+1": "2", "hi": "hi", "21": "41"}[inp]  # regresses on c

    cand = vs.register("code", "regressing variant")
    report = await guard.evaluate(cand.body, bad_run, baseline_pass_rate=1.0)
    assert not report.ok, "canary failed to reject a regression"
    # Invariant: accept() must NOT be called on rejected variants.
    if report.ok:
        vs.accept(cand.id)
    got = vs.get(cand.id)
    assert got is not None and not got.accepted
    print("canary-rejects-regression OK")

asyncio.run(main())
PYEOF

echo "== kill-gate check: daily pass-rate monotonicity helper works =="
$PY - <<'PYEOF'
import math, tempfile, time
from pathlib import Path
from hypha.reflection.run_log import Run, RunLog

tmp = Path(tempfile.mkdtemp())
rl = RunLog(tmp / "runs.db")

# Simulate 14 days with a STRICTLY non-monotonic decline (day 7 dips).
now = time.time()
plan = [0.6, 0.65, 0.7, 0.72, 0.74, 0.76, 0.78,
        0.60, 0.79, 0.80, 0.82, 0.83, 0.85, 0.87]  # day 8 is a dip
for i, target in enumerate(plan):
    day_start = now - (13 - i) * 86400 + 3600
    # 10 runs per day at the target rate.
    total = 10
    passed = round(total * target)
    for j in range(total):
        rl.append(Run(agent="a", prompt_id="code", variant_id="v1",
                      model="m", tokens_in=0, tokens_out=0,
                      verification_passed=j < passed, ms=1))
        # fudge ts into the day bucket
        import sqlite3
        with sqlite3.connect(rl.path) as db:
            db.execute("UPDATE runs SET ts = ? WHERE id = (SELECT id FROM runs ORDER BY ts DESC LIMIT 1)",
                       (day_start + j * 10,))

rates = rl.daily_pass_rate("v1", days=14)
print("daily rates:", [f"{r:.2f}" for r in rates])
monotonic = all(rates[i] <= rates[i+1] for i in range(len(rates) - 1) if rates[i] >= 0 and rates[i+1] >= 0)
assert not monotonic, "planted non-monotonicity not detected"
print("kill-gate helper correctly flags non-monotonic series")
PYEOF

echo "== security self-check =="
# Accept path in VariantStore never called implicitly from Clusterer.
# (The clusterer only emits PromptVariantCandidate; accept() is a separate
# step gated by canary. Grep verifies no vs.accept in clusterer.)
if grep -E 'accept\(' hypha/reflection/clustering.py ; then
  echo "FAIL: clusterer must not call accept"; exit 1
fi
# CanaryGuard refuses empty task list (no free accept).
grep -q "at least one task" hypha/reflection/canary.py
echo "security OK"

echo "verify_m6 PASS"
