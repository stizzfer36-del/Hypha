# Hypha — operator notes

## Thesis

Repo as autonomous organism. Human is one input channel among many. Do not
treat Hypha as an editor, a chatbot, or a tool the human invokes. Every
design choice honors this or is wrong.

## Invariants (do not violate without re-planning)

- **Ledger is the single source of truth.** Every component reads and writes
  events there. No side-state.
- **Events, not RPC.** Components publish and subscribe to typed events;
  nothing calls another component directly across the bus.
- **Reversibility by construction.** All code execution happens on a git
  worktree, never the main checkout. Merges require explicit human accept
  (or `HYPHA_AUTO_ACCEPT=1` canary mode — use with care).
- **Canary-guard before reflection.** Prompt/tool evolution cannot ship a
  variant that regresses the held-out canary set, regardless of main-metric
  gain. `hypha/reflection/clustering.py` never calls `VariantStore.accept()`
  — that's the canary's gate.
- **One repo per daemon.** Multi-repo is a product concern, not a milestone.
- **No silent sandbox fallback.** `hypha/sandbox/firejail.py` raises when
  firejail is missing rather than running unsandboxed. If you need M1–M4
  semantics without sandboxing, set up the pipeline to run the fused agent
  directly instead of the supervisor's verifier.
- **ff-only merges.** `hypha/surface/diff_approval.py` refuses to create a
  merge commit. If the base moved during the patch window, the approval
  downgrades to a reject with ff-failure as rationale.

## Module status (fully built — no stubs)

| M | Modules | Built |
|---|---------|-------|
| 1 | ledger.py, daemon.py, cli.py, config.py, surface/status.py | yes |
| 2 | context/ast_index.py, context/git_history.py, context/joint_query.py | yes |
| 3 | agents/fused.py, agents/_patch.py, sandbox/worktree.py, verify/pytest_runner.py, verify/typecheck.py | yes |
| 4 | events.py, bus.py (Redis + InMemory), router.py (+ OpenAI-compatible providers) | yes |
| 5 | sandbox/firejail.py, sandbox/hypha.profile, surface/diff_approval.py | yes |
| 6 | reflection/run_log.py, variants.py, canary.py, clustering.py, agents/{planner,coder,verifier,archivist}.py | yes |
| 7 | devices/claim.py, devices/heartbeat.py | yes |
| 8 | context/runtime_traces.py, context/embeddings.py, verify/pytest_plugin.py, context/joint_query.py (v2) | yes |
| + | supervisor.py, telegram_bridge.py, verify/behavioral_diff.py | yes |

## Daemon composition

`hypha daemon` runs these concurrent tasks:

1. Ledger tailer — prints new events to stdout.
2. Supervisor — drains `IntentCreated` through `Planner → Coder → Verifier →
   Archivist`. Cursor persists at `<db-parent>/supervisor.cursor`, so
   restarts don't replay.
3. Heartbeat (optional) — if `HYPHA_DEVICE_ID` is set, registers in the
   claims DB and publishes `DeviceHeartbeat` events.
4. On SIGINT/SIGTERM: releases any claims this device owns, emits
   `DaemonStopped`, closes cleanly.

## Kill criteria (stop and report, do not push through)

- Post-M4: p50 intent latency > 10 min → zero-budget constraint may be dead.
- Post-M5: false-pass rate > 15% on 20-intent suite → stop automating.
- Post-M6: canary pass rate not monotonic over 14 days → rethink reflection.
- Post-M8: four-layer engine context-starved on real repo → add
  tool-use-at-retrieval.

## Running

```bash
source .venv/bin/activate
hypha daemon                       # long-running supervisor
hypha intent "<text>"              # add intent from another shell
hypha events --limit 20            # recent ledger view
hypha accept <id-prefix>           # approve a passing diff
hypha reject <id-prefix>           # reject a passing diff
hypha telegram                     # optional Telegram bridge
```

Env vars:
- `HYPHA_DB_PATH` — ledger location. Defaults to `./hypha.db`.
- `HYPHA_AUTO_ACCEPT=1` — supervisor ff-merges every passing diff.
- `HYPHA_DEVICE_ID`, `HYPHA_DEVICE_TAGS` — join a multi-device mesh.
- `HYPHA_BASE_BRANCH` — defaults to `main`.
- `HYPHA_TRACE_DB` — set at pytest time to record spans into the joint store
  (enables the M8 runtime-trace layer).
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — allowed chat is a hard gate.
- `GROQ_API_KEY`, `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY` — providers the
  router may route to; unset providers are silently skipped.

## Security checklist (walked at every commit)

Baseline:
- `.env` is gitignored and not staged.
- No API keys or tokens in committed files, logs, or event payloads.
- Parameterized SQL only.
- Paths from env resolved and confined to expected roots.
- No `subprocess(..., shell=True)`.

Per-layer:
- **Sandbox** — firejail profile reviewed; cwd must be under
  `.hypha/worktrees/`; missing binary fails loudly.
- **Router** — API keys only in `.env`; never printed; payload cap on the
  bus; unset keys silently skip the provider.
- **Reflection** — `VariantStore.accept()` only called when
  `CanaryReport.ok`; clusterer has no `accept()` call (grep-enforced).
- **Devices** — claim is atomic (SQL primary key + IntegrityError ->
  conflict); release scoped to owner; stale heartbeat releases with an
  audit trail.
- **Runtime traces** — attrs redacted (secret-ish keys + tokenish values)
  before storage.
- **Telegram** — only `TELEGRAM_CHAT_ID` may interact; everything else
  silently dropped.

Run `bash scripts/verify_all.sh` to walk every milestone's checks plus the
full test suite and a grep-based "no NotImplementedError in `hypha/`" gate.
