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
`codex exec --sandbox read-only`. First, run `.venv/bin/python scripts/codex_smoke.py` once to
confirm the flags and capture a real output sample. No other network calls.

## Demo scenarios (watch the loop phase by phase)

Every run now narrates itself live — `A Actor → B Enforce → C Tests → D QA →
E Security → verdict` — to the terminal, and (when Slack env is set) as a threaded
status stream. The presenter's script is [`docs/DEMO-RUNBOOK.md`](docs/DEMO-RUNBOOK.md).
The arc: *it just works → it fixes its own mistake → it knows when to stop.*

| Scenario | Target | Outcome |
|----------|--------|---------|
| Protected-path revert (deterministic vignette) | `scripts/demo_protected_path.py` | tamper caught & reverted, then converge |
| 1-iteration success | `demo/website` | converges first try (static site) |
| Self-correction (~2 iterations) | `demo/bankapp` + `specs/transfer-limit-terse.md` | fails a gate, self-corrects, converges |
| Escalation at the cap | `demo/impossible` | contradictory spec → never converges → escalates |
| Self-authored gate | `demo/greenfield-transfer` + `--gate synthesize` | test-author agent writes the gate from the spec, then the loop implements against it |

New CLI flags: `--max-iterations N` (per-run cap, clamped to the hard ceiling of 6),
`--constitution PATH` (default: the repo's own `constitution.md`, else
`skills/constitution.md`), and `--gate synthesize` (phase 0: an independent
test-author agent writes the acceptance gate from the spec before the loop;
default `provided`). Slack status stream is opt-in via `SLACK_BOT_TOKEN` +
`SLACK_CHANNEL` (channel ID); see the runbook.

## Safety properties

- Bounded: `MAX_ITERATIONS=6`, `MAX_WALL_SECONDS=1200` (owned by our code).
- Read-only verification: tests + constitution are read-only to the actor; tampering
  is detected via `git diff` and reverted.
- Deterministic-first: pytest decides pass/fail before any LLM critic is spent.
- No auto-merge: convergence produces a PR artifact for a human gate.

See `docs/superpowers/specs/2026-06-28-agentic-loop-design.md` §13 for the honest caveats.
