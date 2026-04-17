# Hypha

Persistent in-repo autonomous organism. The repo is the substrate; the system
is the mycelium. You don't open Hypha to code — Hypha is already working,
and you check in.

## Status

All 8 milestones implemented and tested (58 tests pass).

## Run

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,context,bus]"
cp .env.example .env           # set HYPHA_DB_PATH, optionally provider keys
hypha intent "make the auth flow idempotent"
hypha events
hypha status
python -m hypha.daemon &       # long-running loop, another shell
```

## Milestones

| # | Module(s) | Verify |
|---|-----------|--------|
| 1 | ledger + daemon + CLI | `scripts/verify_m1.sh` |
| 2 | context engine v1 (AST + git) | `scripts/verify_m2.sh` |
| 3 | plan-code-verify loop on worktree | `scripts/verify_m3.sh` |
| 4 | model router + event bus | `scripts/verify_m4.sh` |
| 5 | firejail sandbox + diff approval | `scripts/verify_m5.sh` |
| 6 | self-improvement + canary | `scripts/verify_m6.sh` |
| 7 | multi-device claim + heartbeat | `scripts/verify_m7.sh` |
| 8 | context engine v2 (runtime + embeddings) | `scripts/verify_m8.sh` |

See `AGENTS.md` for operator notes and kill criteria.
