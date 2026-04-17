#!/usr/bin/env bash
# Full-repo verify: every milestone's verify script + the complete test suite.
#   PY=.venv/bin/python HYPHA=.venv/bin/hypha bash scripts/verify_all.sh
set -euo pipefail

PY=${PY:-python}
HYPHA=${HYPHA:-hypha}

echo "== complete pytest suite =="
$PY -m pytest -q

echo
echo "== per-milestone verify scripts =="
for m in 1 2 3 4 5 6 7 8; do
  echo
  echo "-- M$m --"
  PY="$PY" HYPHA="$HYPHA" bash "scripts/verify_m${m}.sh"
done

echo
echo "== repo is fully built (no stubs) =="
if grep -RE 'raise NotImplementedError' hypha/ ; then
  echo "FAIL: NotImplementedError still present in hypha/"
  exit 1
fi
echo "no stubs remain"

echo
echo "verify_all PASS"
