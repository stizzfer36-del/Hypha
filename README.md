# Hypha

Persistent in-repo autonomous organism. The repo is the substrate; the
system is the mycelium. You don't open Hypha to code — Hypha is already
working, and you check in.

## Status

Fully built. **84 tests pass.** Zero `NotImplementedError` stubs.
See `scripts/verify_all.sh`.

## Install

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,context,bus,telegram]"
cp .env.example .env        # set HYPHA_DB_PATH, optionally provider keys
```

Optional system packages:
- **firejail** — needed to actually sandbox code execution at M5.
- **redis** — only if you want cross-process / multi-device event fanout.

## Use

```bash
# Record an intent and watch the ledger breathe.
hypha intent "make the auth flow idempotent"
hypha events --limit 20
hypha status

# Run the supervisor: it plans -> codes -> verifies every new intent.
hypha daemon

# Approve a passing verification (8-char prefix of the event id):
hypha accept a1b2c3d4
hypha reject a1b2c3d4

# Or run the Telegram bridge as a second surface.
hypha telegram
```

To auto-accept passing diffs (canary mode, use with care):

```bash
HYPHA_AUTO_ACCEPT=1 hypha daemon
```

To join a multi-device mesh:

```bash
HYPHA_DEVICE_ID=pi-01 HYPHA_DEVICE_TAGS=always-on,gpu hypha daemon
```

## Architecture

| Layer | Files | What it does |
|-------|-------|--------------|
| Ledger | `hypha/ledger.py` | Append-only SQLite event log — single source of truth. |
| Surface | `hypha/cli.py`, `hypha/telegram_bridge.py`, `hypha/surface/` | Human-facing inputs and outputs. Same event contract on every surface. |
| Context engine | `hypha/context/` | Four-layer joint query over AST, git history, runtime traces, embeddings. |
| Agents | `hypha/agents/` | Planner, coder, verifier, archivist — and a fused fallback. |
| Sandbox | `hypha/sandbox/` | `git worktree` per task + firejail profile. |
| Verification | `hypha/verify/` | pytest runner, mypy, behavioral diff via JUnit XML replay. |
| Bus | `hypha/bus.py` | Redis Streams (prod) or in-memory (tests). |
| Router | `hypha/router.py` | Cost-latency-capability fallback across Groq/DeepSeek/OpenRouter. |
| Reflection | `hypha/reflection/` | Run log + clustering + variant store + **non-negotiable canary guard**. |
| Devices | `hypha/devices/` | Optimistic-lock claims + heartbeat. |
| Supervisor | `hypha/supervisor.py` | Subscribes to the ledger; turns an IntentCreated into a merged commit. |

## Milestones

| # | Deliverable | Tests | Verify |
|---|-------------|-------|--------|
| 1 | ledger + daemon + CLI | 7 | `scripts/verify_m1.sh` |
| 2 | context engine v1 (AST + git) | 5 | `scripts/verify_m2.sh` |
| 3 | plan-code-verify loop on worktree | 4 | `scripts/verify_m3.sh` |
| 4 | model router + event bus | 10 | `scripts/verify_m4.sh` |
| 5 | firejail sandbox + diff approval | 8 | `scripts/verify_m5.sh` |
| 6 | self-improvement + canary | 11 | `scripts/verify_m6.sh` |
| 7 | multi-device claim + heartbeat | 6 | `scripts/verify_m7.sh` |
| 8 | context v2 (runtime + embeddings, 4-layer) | 7 | `scripts/verify_m8.sh` |
| + | split agents, supervisor, telegram, CLI, pytest plugin | 26 | see `tests/` |

Full run: `bash scripts/verify_all.sh`.

## Kill criteria (reproduced from the spec, enforced during operation)

- **Post-M4:** p50 intent latency > 10 min → zero-budget constraint may be
  dead. Re-plan before adding more load.
- **Post-M5:** verification false-pass rate > 15% on a 20-intent suite → stop
  automating.
- **Post-M6:** canary pass rate not monotonic over 14 days → rethink
  reflection before adding multi-device load.
- **Post-M8:** four-layer engine still produces context-starved diffs on a
  real repo → add tool-use-at-retrieval before declaring v2 shipped.

`hypha/reflection/canary.py` is the only defense against prompt-evolution
reward-hacking; it is non-negotiable. `hypha/reflection/clustering.py`
never calls `VariantStore.accept()` — that's the canary's gate.

## Layout

```
Hypha/
├── hypha/
│   ├── cli.py                       CLI commands (intent, events, status, accept, reject, daemon, telegram)
│   ├── config.py                    .env -> Config
│   ├── daemon.py                    asyncio entrypoint (tails ledger + runs supervisor + heartbeats)
│   ├── ledger.py                    append-only SQLite event log
│   ├── events.py                    Kind enum — one authoritative event taxonomy
│   ├── bus.py                       Redis Streams Bus + InMemoryBus for tests
│   ├── router.py                    provider-driven Router with RateLimited/Transient fallback
│   ├── supervisor.py                plan -> code -> verify -> approve loop
│   ├── telegram_bridge.py           Telegram surface (intent/events/status/accept/reject)
│   ├── agents/
│   │   ├── _patch.py                shared JSON-patch parser/applier
│   │   ├── fused.py                 single-agent loop (day-one path)
│   │   ├── planner.py               split: decompose intent into subgoals
│   │   ├── coder.py                 split: apply JSON patch on a worktree
│   │   ├── verifier.py              split: pytest + mypy + behavioral_diff
│   │   └── archivist.py             split: approve-and-merge + missing-tool clusters
│   ├── context/
│   │   ├── ast_index.py             tree-sitter Python walker -> ast_symbols
│   │   ├── git_history.py           pygit2 log + co-change -> git_* tables
│   │   ├── runtime_traces.py        span capture (with secret redaction)
│   │   ├── embeddings.py            HashEncoder (default) + MiniLMEncoder (opt-in)
│   │   └── joint_query.py           four-layer joint rank
│   ├── reflection/
│   │   ├── run_log.py               per-agent-run history + daily pass rate
│   │   ├── variants.py              prompt-variant registry with freeze window
│   │   ├── canary.py                held-out guard — rejects any regression
│   │   └── clustering.py            nightly reflection: failure clusters -> candidates
│   ├── devices/
│   │   ├── claim.py                 optimistic-lock claims + release_stale
│   │   └── heartbeat.py             periodic heartbeat upserts
│   ├── sandbox/
│   │   ├── worktree.py              git worktree per task under .hypha/worktrees/
│   │   ├── firejail.py              argv builder + cwd-escape refusal + missing-bin detection
│   │   └── hypha.profile            shipped firejail profile (caps.drop, seccomp, netfilter)
│   ├── verify/
│   │   ├── pytest_runner.py         pytest subprocess wrapper
│   │   ├── typecheck.py             mypy wrapper (skip if unconfigured)
│   │   ├── behavioral_diff.py       JUnit XML pre/post diff (regressions vs improvements)
│   │   └── pytest_plugin.py         HYPHA_TRACE_DB=... -> auto-capture spans
│   └── surface/
│       ├── status.py                "what is Hypha doing right now"
│       └── diff_approval.py         render diff + ff-only merge on accept
├── tests/                           pytest suite
├── scripts/
│   ├── verify_m{1..8}.sh            per-milestone end-to-end
│   └── verify_all.sh                full sweep + zero-stubs check
├── pyproject.toml
├── .env.example
├── AGENTS.md                        operator notes + invariants
└── README.md                        this file
```
