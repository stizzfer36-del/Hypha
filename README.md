# Hypha

Persistent in-repo autonomous organism. The repo is the substrate; the system
is the mycelium. You don't open Hypha to code — Hypha is already working,
and you check in.

## Status

Scaffolded. Milestone 1 (ledger + daemon + CLI) is next.

## Run (M1, once implemented)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # edit HYPHA_DB_PATH if desired
hypha intent "make the auth flow idempotent"
hypha events
```

## Milestones

See `/root/.claude/plans/hypha-phase-glowing-lemur.md` for the plan. See
`AGENTS.md` for operator notes.
