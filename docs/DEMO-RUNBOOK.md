# loopEngineer — Demo Runbook

A presenter's script for showing the agentic loop **phase by phase** to an
audience, plus the loop↔Slack status stream. Read this top to bottom once before
you present; then run the scenarios in the order below.

The arc is deliberate: **it just works → it fixes its own mistake → it knows when
to stop.** Don't lead with a failure.

| # | Scenario | Command target | Expected | Reliability |
|---|----------|----------------|----------|-------------|
| 0 | Safety vignette: protected-path revert | `scripts/demo_protected_path.py` | tamper caught & reverted, then converge | **Deterministic** (scripted mock) |
| 1 | 1-iteration success | `demo/website` | converges on attempt 1 | High |
| 2 | Self-correction (~2 iterations) | `demo/bankapp` (terse spec) | fails once, fixes, converges | Typical, **not guaranteed** — record it |
| 3 | Escalation at the cap | `demo/impossible` | never converges → escalates | **Deterministic** (fails the test gate every time) |
| 4 | Self-authored gate (spec → tests → code) | `demo/greenfield-transfer` | loop writes its own gate, then converges | High (record it) |

> **Golden rule:** rehearse every scenario on the demo machine the day before and
> screen-record each run into `demo/recordings/`. Real agents are
> non-deterministic; if a live run drifts, cut to the recording and keep talking.
> Scenarios 0 and 3 are deterministic; 1 is high-probability; **2 is the one most
> likely to surprise you** — never present it without a recording in your pocket.

---

## Board-driven flow (Taiga + loop-hub) — the headline demo

The 2026-07 build added `loop-hub` (in the main hackathon repo, `loopHub/`):
the board drives everything and the CLI scenarios below become the fallback.
Rehearsed end-to-end 2026-07-09; measured timings in the table.

**Start the stack (before the audience):**

```bash
# 1. Taiga (from taiga-docker/): docker compose up -d   → UI on localhost:9000
# 2. loop-hub (from loopHub/):
set -a; source .env; set +a
uv run --with fastapi --with uvicorn --with httpx python -m hub   # port 8400
# sanity: startup log must show "resolved status ids" for all 3 projects
```

**The three acts, all driven by dragging cards in the Taiga UI (payments-board):**

| Act | Card | What the audience sees | Measured |
|-----|------|------------------------|----------|
| 一次就過 | PM story + `repo=bankapp`, drag Backlog→Spec Drafting | AI spec lands in the card (~1m35s), auto-moves to Spec Review with @reviewer comment; reviewer resolves Open questions, drags to Dev; loop converges; card lands in PR-Done with the PR artifact | spec 1m35s + loop 3m13s |
| 自我修正 | reviewer replaces spec with `demo/bankapp/specs/transfer-limit-terse.md`, approves | loop fails a gate on attempt 1, self-corrects, converges (2 iterations) | 5m09s |
| 知所進退 | reviewer replaces spec with `demo/impossible/specs/*` (contradictory), approves | loop exhausts the cap, card returns to Spec Review with the failure report as a comment — safe refusal | 6m07s |

**Guardrail beats to show between acts (each is one drag):**
- Drag a Backlog card straight to Dev → bounced back with a ⛔ comment.
- Approve a spec that still has *Open questions* → bounced back to Spec Review.
- Drag Spec Review→Spec Drafting without leaving a comment → bounced (feedback required).

**The live failure drill (rehearsed, works):** kill loop-hub mid-demo
(`kill $(lsof -ti :8400)`), drag a card into Spec Drafting while it's down
(webhook lost — Taiga does not retry), restart loop-hub — within 60 s the
reconciliation poller logs `poller: re-enqueued story N` and the draft appears.
Say: "no event is load-bearing; the board state is."

**Reset between rehearsals:** move cards back to Backlog (never delete — the
comment history is part of the story) and `rm loopHub/loop-hub.sqlite3` if you
want a clean queue.

**Gotchas already hit so you don't re-hit them:**
- Taiga webhooks silently fail unless taiga-back/async have
  `WEBHOOKS_ENABLED=True` **and** `WEBHOOKS_ALLOW_PRIVATE_ADDRESS=True`
  (the infra doc's `WEBHOOKS_BLOCK_PRIVATE_ADDRESS` name does not exist).
  Check Project → Settings → Integrations → webhook logs when in doubt.
- If Docker Desktop restarts, `docker compose up -d` in taiga-docker/ brings
  Taiga back with all data (volumes persist), then restart loop-hub.
- `codex` CLI is not on this machine — everything runs `--agent claude`.

---

## The five phases (put this slide up before you run anything)

Every iteration runs the same five stages. The agent only does **A**; *our* code
does **B–E** and the gating.

| | Phase | Plain English |
|---|-------|---------------|
| **A** | Actor | the agent writes code in an isolated worktree |
| **B** | Enforce | our code checks it didn't touch the tests or the constitution (and reverts it if it did) |
| **C** | Tests | *we* run pytest — the objective, deterministic gate |
| **D** | QA | a read-only critic judges whether the spec is genuinely met |
| **E** | Security | a read-only critic checks the change against the constitution |

All five must pass **in the same iteration** to converge. Any failure feeds the
reason back to the next attempt. The loop is bounded (`MAX_ITERATIONS = 6`,
`MAX_WALL_SECONDS = 1200`) and never auto-merges — it produces a PR artifact for a
human.

---

## One-time setup (do this before the audience arrives)

```bash
# from the repo root
python3 -m venv .venv && .venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q          # sanity: everything green (1 skipped is fine)
```

Pick the agent backend:
- **Dev machine (Claude Code):** `--agent claude` (default). Needs the `claude` CLI on PATH.
- **Work machine (Codex):** `--agent codex`. Run `.venv/bin/python scripts/codex_smoke.py` once first.

### Slack status stream (optional but recommended for the Slack part)

The loop posts a threaded status stream when **both** env vars are set; otherwise
it prints to the terminal only.

```bash
export SLACK_BOT_TOKEN=xoxb-...        # a bot token with chat:write
export SLACK_CHANNEL=C0XXXXXXX         # the channel ID (not the name)
```

- Invite the bot to the channel: `/invite @your-bot` in Slack.
- Required scope: `chat:write`.
- Put the Slack channel on screen next to your terminal. Each run appears as a
  **root message** with one **threaded reply per iteration** and a final
  ✅ *Converged* / 🚨 *Escalated* verdict. **Pair the Slack view with Scenario 3**
  — an escalation landing in the channel is the compelling "a human is now on the
  hook" moment.

---

## Scenario 0 — Safety vignette: the guard that catches a cheat (deterministic)

**Say:** "First, the safety property everything else rests on. What if the agent
tries to weaken a test to make its code pass? Watch phase B."

```bash
.venv/bin/python scripts/demo_protected_path.py
```

**What they see:** attempt 1 — `B Enforce ✗ Actor modified protected files:
['tests/test_transfer.py']` → retry. Attempt 2 — the agent plays it straight,
all gates pass, converged. This one is a **scripted mock** on purpose (a real
model won't tamper on cue) — say so; it's the honest way to show the guard fire
every time.

---

## Scenario 1 — "It just works" (1 iteration)

**Say:** "A simple, well-specified task: build a basic landing page. The tests
define done; the agent writes it; the gates pass first try."

```bash
.venv/bin/python -m loopengine run \
  --spec demo/website/specs/landing-page.md \
  --repo demo/website \
  --agent claude
```

**What they see:** one iteration, A→B→C→D→E all green, `⇒ CONVERGED`.
**Close the loop:** open the PR artifact printed on the last line and show the diff
— make it concrete.

```bash
# open the built page too, so "done" is visible, not abstract
open demo/website/index.html            # macOS
cat runs/<run-id>/pr-artifact.md        # the human-merge report
```

*(The website carries its own `constitution.md`; the security critic enforces the
web rules, not the banking ones. That's the `--constitution` auto-detection.)*

---

## Scenario 2 — "It fixes its own mistake" (~2 iterations) — THE money shot

**Say:** "Now the reason a *loop* beats a one-shot agent. The spec here is
terse — it doesn't spell out the exact-at-limit rule or the money-type rule. Watch
the first attempt trip a gate, read the feedback, and self-correct."

```bash
.venv/bin/python -m loopengine run \
  --spec demo/bankapp/specs/transfer-limit-terse.md \
  --repo demo/bankapp \
  --agent claude
```

**What they see (typical):** attempt 1 fails at **C** (the exact-equal boundary
test) or **E** (used `float`, violating §1); the `⇒ retry` line shows the reason;
attempt 2 converges.

**If it converges in 1 (agent nailed it):** don't panic — say "sometimes it gets
it first try; here's the recorded run where it self-corrects" and play the
recording. **This is why you recorded it.** If it takes 3, that's fine too — narrate
each retry reason.

---

## Scenario 3 — "It knows when to stop" (escalation, deterministic)

**Say:** "Last, the failure mode that matters most: a *broken spec*. This spec
contradicts itself — it demands a refund at the threshold be both allowed and
denied. No code can satisfy the tests. Watch the system refuse to ship a guess
and escalate instead of looping forever."

Run it at a **smaller cap** so the audience isn't watching six failures — the
lesson is identical at 3 and half the wall-clock:

```bash
.venv/bin/python -m loopengine run \
  --spec demo/impossible/specs/instant-refund.md \
  --repo demo/impossible \
  --agent claude \
  --max-iterations 3
```

(Drop `--max-iterations 3` if you specifically want to show the real ceiling of 6;
expect it to take noticeably longer — lean on the recording for the full-6 version.)

**What they see:** every iteration fails at **C** (the contradictory tests), each
`⇒ retry` shows the same unwinnable failure, then `⇒ ESCALATED — iteration cap`.
**With Slack on**, the 🚨 *Escalated* verdict lands in the channel — that's your
human-in-the-loop beat: the loop gave up safely and pinged a human.

---

## Scenario 4 — "It writes its own gate" (spec → tests → code)

**Say:** "Everything so far graded the agent against tests a human wrote. This
repo has NO tests at all — only an approved spec. Watch phase 0: an independent
test-author agent turns the spec into the acceptance gate, our code verifies
the gate is real — it must fail on the unimplemented code, cover every
acceptance criterion, and be deterministic — freezes it, and only then does the
actor implement against it. The only human step left is approving the spec."

```bash
.venv/bin/python -m loopengine run \
  --spec demo/greenfield-transfer/specs/daily-limit.md \
  --repo demo/greenfield-transfer \
  --agent claude \
  --gate synthesize
```

**What they see:** `G Gate` lines first — authoring, verification, then
`G Gate ✓ frozen: 1 test file(s) · 4 red on baseline → gate/<run-id>` — followed
by the normal iteration loop converging against the gate it just wrote.

**Close the loop:** open the PR artifact (implementation-only diff) and show
`git show gate/<run-id>:tests/acceptance/test_daily_limit.py` (run inside
`demo/greenfield-transfer`) — the tests the loop wrote and was graded against.
Point out the actor could not edit them (phase B), and the vacuity check proved
they were red before implementation.

**If gate synthesis fails live:** that IS the safety story — the run escalates
and the loop never starts. Narrate it and rerun (or cut to the recording).

---

## Talking points to land

- **The agent proposes; our code disposes.** Phases B–E and the caps are ours; the
  agent has no say over them. (`config.py` owns the caps; critics are read-only.)
- **Deterministic before subjective.** pytest (C) runs before the LLM critics (D,
  E) — objective truth first, and we never spend a critic on code that fails tests.
- **No auto-merge.** Convergence produces `runs/<run-id>/pr-artifact.md` for a
  human to review and merge. The loop never pushes.
- **Everything is auditable.** `runs/<run-id>/state.json` records every phase of
  every iteration; `tail -f` it during a run if someone wants the raw spine.

## Reusing this for other demos later

The engine is domain-agnostic. To add a scenario: write a `spec.md`, an incomplete
repo, read-only `tests/` that define "done", and (optionally) a repo-local
`constitution.md`. Then `run --spec ... --repo ...`. The website domain is the
template for non-banking demos.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No Slack messages | Check both `SLACK_BOT_TOKEN` and `SLACK_CHANNEL` (channel **ID**) are exported, the bot is invited, and it has `chat:write`. Failures print `[slack] ...` and never break the loop. |
| Scenario 1 takes 2+ iterations | The agent hit a real gap; narrate it, or cut to the recording. It's still a valid story. |
| Scenario 2 converges in 1 | Expected sometimes — play the recorded self-correction run. |
| A run hangs on the actor | The real agent is thinking; the wall-cap (1200s) will escalate. For demos, prefer the recording over waiting. |
| `git worktree` error on rerun | A previous run left a worktree; `git worktree prune` in the demo repo, or delete `.worktrees/`. |
