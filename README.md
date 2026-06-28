# loopEngineer — a controlled spec-to-PR agentic loop

A runnable prototype of a bounded Codex Actor↔Critic loop. It ingests a
pre-approved `spec.md` and iterates (write → enforce → test → QA → security)
until it converges on a reviewed, constitution-compliant change — a local PR
artifact for a human to merge — or escalates safely at the iteration/time cap.

## The 5 + memory building blocks (one module each)

| Block | Module | Job |
|-------|--------|-----|
| Automations | `loopengine/trigger.py` | manual entrypoint; ingest spec.md; own the caps |
| Worktrees | `loopengine/isolation.py` | isolated git worktree + protected-path enforcement |
| Skills | `skills/` | constitution + prompts, read-only to the actor |
| Connectors | `loopengine/connectors.py` | pytest gate, git helpers, PR artifact |
| Sub-agents | `loopengine/agents.py` | Codex actor (write) + QA/security critics (read-only) |
| Memory | `loopengine/memory.py` | durable per-run state; the loop's spine |

`loopengine/orchestrator.py` is thin glue. See `docs/superpowers/specs/` for the design.

> Setup (once): `python3.13 -m venv .venv && .venv/bin/python -m pip install pytest`.
> All commands below use `.venv/bin/python` (Python 3.13). On the work machine,
> use whatever 3.11+ interpreter has pytest.

## Run the offline test suite (mock agent, no keys)

```bash
.venv/bin/python -m pytest -q            # the prototype's own tests, incl. the 3-attempt demo
```

## Run for real on THIS dev machine (Claude Code)

```bash
.venv/bin/python -m loopengine run \
  --spec demo/bankapp/specs/transfer-limit.md \
  --repo demo/bankapp \
  --agent claude        # default; verifies every loop step with a real agent
```

Optional live end-to-end test: `LOOP_LIVE=claude .venv/bin/python -m pytest tests/test_live_claude.py -v`.

## Run for the demo on the work machine (Codex CLI)

```bash
.venv/bin/python -m loopengine run \
  --spec demo/bankapp/specs/transfer-limit.md \
  --repo demo/bankapp \
  --agent codex
```

Actor runs `codex exec --sandbox workspace-write`; critics run
`codex exec --sandbox read-only`. First, run `python scripts/codex_smoke.py` once to
confirm the flags and capture a real output sample. No other network calls.

## Safety properties

- Bounded: `MAX_ITERATIONS=6`, `MAX_WALL_SECONDS=1200` (owned by our code).
- Read-only verification: tests + constitution are read-only to the actor; tampering
  is detected via `git diff` and reverted.
- Deterministic-first: pytest decides pass/fail before any LLM critic is spent.
- No auto-merge: convergence produces a PR artifact for a human gate.

See `docs/superpowers/specs/2026-06-28-agentic-loop-design.md` §13 for the honest caveats.
