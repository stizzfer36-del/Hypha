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
  worktree, never the main checkout. Merges require explicit human accept.
- **Canary-guard before reflection.** Prompt/tool evolution (M6) cannot ship
  a variant that regresses the held-out canary set, regardless of main-metric
  gain.
- **One repo per daemon.** Multi-repo is a product concern, not a milestone.

## Milestone map

| M | Module(s) | Built? |
|---|-----------|--------|
| 1 | `ledger.py`, `daemon.py`, `cli.py`, `config.py`, `surface/status.py` | yes |
| 2 | `context/ast_index.py`, `context/git_history.py`, `context/joint_query.py` | yes |
| 3 | `agents/fused.py`, `verify/pytest_runner.py`, `verify/typecheck.py`, `sandbox/worktree.py` | yes |
| 4 | `events.py`, `bus.py`, `router.py` | yes |
| 5 | `sandbox/firejail.py`, `surface/diff_approval.py`, `sandbox/hypha.profile` | yes |
| 6 | `reflection/*` (canary is non-negotiable) | yes |
| 7 | `devices/heartbeat.py`, `devices/claim.py` | yes |
| 8 | `context/runtime_traces.py`, `context/embeddings.py`, `context/joint_query.py` v2 | yes |

## Kill criteria (stop and report, do not push through)

- Post-M4: p50 intent latency > 10 min → zero-budget constraint may be dead.
- Post-M5: false-pass rate > 15% on 20-intent suite → stop automating.
- Post-M6: canary pass rate not monotonic over 14 days → rethink reflection.
- Post-M8: four-layer engine context-starved on real repo → add
  tool-use-at-retrieval.

## Running (M1, once built)

```bash
source .venv/bin/activate
python -m hypha.daemon          # long-running daemon
hypha intent "<text>"           # add intent from another shell
hypha events --limit 20         # recent ledger view
hypha status                    # what is Hypha doing right now
```

## Security checklist (walked at every milestone commit)

See the table in the plan file for per-milestone specifics. Baseline every
commit:
- `.env` is gitignored and not staged.
- No API keys or tokens appear in committed files, logs, or event payloads.
- Parameterized SQL only. No string-formatted queries.
- Paths from env vars are resolved and confined to expected roots.
- No subprocess shell=True without a reviewed, fixed command.
