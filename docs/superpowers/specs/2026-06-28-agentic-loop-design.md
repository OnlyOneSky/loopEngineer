# Spec-to-PR agentic loop — design

> Status: design for review (pre-implementation)
> Date: 2026-06-28
> Project folder: `loopEngineer/`
> Knowledge reference: `SecondBrain/` (Loop Engineering notes + Hackathon 2026 reference impl)

## 1. Purpose

Build a **runnable prototype** that ingests a pre-generated `spec.md` and runs a
**controlled Actor↔Critic agentic loop** to completion, producing a reviewed,
constitution-compliant change for a human to merge.

The prototype is deliberately architected so that **each of the "5 + memory"
loop-engineering building blocks is its own module** — the code layout itself is
the teaching tool for exploring what an agentic loop is made of.

This is the engine behind the Cathay AI Hackathon proposal's "看板驅動的 Agentic
Loop" (Kanban-driven agentic loop), minus the board/PR/CI plumbing. The board
card-move that triggers the loop in production is replaced here by a manual CLI
invocation against `spec.md`.

## 2. Goals / non-goals

### Goals
- Take a human-approved `spec.md` (produced upstream by a spec-kit / spec-it–style
  plugin) and run the loop end-to-end against a real codebase with a **real test
  gate (pytest)**.
- Make all six building blocks **visible, isolated, and independently
  understandable**: Automations, Worktrees, Skills, Connectors, Sub-agents, Memory.
- Use **Codex CLI only** for all model work (the only agent tool permitted inside
  the company network). Actor and both Critics are `codex exec` invocations.
- Demonstrate the safety story: bounded iterations, read-only verification,
  tamper detection + rollback, deterministic-before-subjective gating, and a
  human merge handoff.
- Ship a **self-contained demo** (transfer-limit banking feature) that the loop
  can actually run and converge on, including a security-critic catch.

### Non-goals (explicitly out of scope for the prototype)
- Kanban connector / webhook trigger (Taiga / Jira / Jenkins). Trigger is manual.
- Real GitHub PR creation or merge. Convergence produces a local PR **artifact**.
- CI dispatch. Tests run locally via pytest.
- The upstream Spec-generation stage and human gate #1 (spec review) — `spec.md`
  arrives already generated and approved.
- Multi-feature / parallel-run orchestration. One spec, one loop per invocation
  (though worktree isolation keeps the door open for parallelism later).

## 3. Constraints & key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Agent runtime | **Codex CLI only** | Only tool allowed on the company network. |
| Actor execution | `codex exec --sandbox workspace-write` | Edits files on disk in an isolated worktree. |
| Critic execution | `codex exec --sandbox read-only` | The maker/checker split is enforced by the **sandbox**, not just the prompt — a read-only critic physically cannot edit a file. |
| Language | Python | Consistent with the existing `orchestrator.py` reference. |
| Spec format | `spec.md` (markdown) | Passed as raw text to Actor/Critics; no separate parser stage. The security critic receives the full constitution and checks every clause. |
| Test gate | Real `pytest` | The one genuine connector; deterministic truth before any LLM judgment. |
| Output | Local PR artifact (markdown) | Stands in for the human merge gate without GitHub. |
| Loop ownership | Plain Python `for` loop | The orchestrator (our code) decides who runs, in what order, when to retry, and when to stop — the model supplies intelligence, our loop supplies control. |

## 3a. Agent backends & portability (dev here, demo on the work machine)

Development happens on a personal machine with **Claude Code** (no Codex
available/allowed); the **demo runs on the work machine where only Codex CLI is
available**. To keep both honest, all model work goes through one `Agent` seam with
three interchangeable backends sharing an identical contract:

| Backend | Where | Role |
|---|---|---|
| `MockAgent` | anywhere, offline | Scriptable double; powers the deterministic test suite. No network, no keys. |
| `ClaudeAgent` | this dev machine | Real end-to-end runs via headless `claude -p`, so every step is verified with a real agent before the demo. |
| `CodexAgent` | work machine (prod) | Real runs via `codex exec`. The only network-permitted tool there. |

Only the thin subprocess/parse layer differs between `ClaudeAgent` and `CodexAgent`;
the loop, gates, memory, and isolation are shared and identical. Backend is chosen
by a `--agent {mock,claude,codex}` flag (default `claude` on the dev machine).

**Headless invocations (verified against Claude Code CLI guidance):**
- Actor (`ClaudeAgent`): `claude -p "<prompt>" --permission-mode acceptEdits
  --allowedTools "Read,Edit,Write" --max-turns N` run with `cwd=<worktree>`; it edits
  files on disk. Output is not parsed — the disk diff is the source of truth.
- Critic (`ClaudeAgent`): `claude -p "<prompt-with-diff-inline>" --allowedTools "Read"
  --output-format json --model <id>`; parse `json.loads(stdout)["result"]`, then
  extract the JSON verdict from that text. No edit tools ⇒ read-only by construction.
- Codex equivalents unchanged: actor = `codex exec --sandbox workspace-write --json`;
  critic = `codex exec --sandbox read-only --json`.

**De-risking the Codex path (can't run here):** because `CodexAgent` cannot be
exercised on the dev machine, we (a) ship a one-shot `scripts/codex_smoke.py` to run
once on the work machine that confirms the `codex exec` flags and dumps a real
`--json` event stream; (b) save that stream as `tests/fixtures/codex_events.jsonl`
and unit-test `CodexAgent`'s output parsing against the *real* sample here; (c) keep
the read-only-critic contract identical so a green Claude run is strong evidence the
Codex run will behave the same modulo the parse layer.

## 4. Architecture — one module per building block

```
loopEngineer/
├── loopengine/                  # the prototype package
│   ├── config.py                # caps + paths (MAX_ITERATIONS, MAX_WALL_SECONDS, …)
│   ├── trigger.py               # [Automations]  manual entrypoint, ingest spec.md
│   ├── isolation.py             # [Worktrees]    git worktree + protected-path enforcement
│   ├── agents.py                # [Sub-agents]   Agent seam: Mock / Claude / Codex backends
│   ├── connectors.py            # [Connectors]   run_tests (pytest), write_pr_artifact, git
│   ├── memory.py                # [Memory]       durable run-state read/write
│   └── orchestrator.py          # thin glue:     run_loop()
├── skills/                      # [Skills]       codified knowledge (read-only to actor)
│   ├── constitution.md          #                §1–§5 banking rules
│   ├── AGENTS.md                #                Codex project guidance
│   └── prompts/
│       ├── actor.txt
│       ├── qa_critic.txt
│       └── security_critic.txt
├── demo/
│   └── bankapp/                 # the target codebase — its OWN git repo
│       ├── transfer.py          # incomplete/buggy feature the actor must complete
│       ├── tests/test_transfer.py
│       └── specs/transfer-limit.md   # the example spec.md input
├── scripts/
│   └── codex_smoke.py           # one-shot: verify codex flags + capture real --json sample
├── tests/
│   └── fixtures/codex_events.jsonl  # real codex output sample (captured on work machine)
├── runs/                        # memory + artifacts output per run (gitignored)
│   └── <run-id>/state.json + pr-artifact.md
├── docs/superpowers/specs/      # this design doc
└── README.md                    # what a loop is + how to run the demo
```

**Why this layout:** every building block maps to exactly one place. `orchestrator.py`
stays thin — it only sequences calls into the block modules. You can read any
single module and fully answer "what does it do, how do you use it, what does it
depend on."

## 5. The loop flow

`orchestrator.run_loop(spec_path, repo_path)`:

0. **Trigger** `[Automations]` — read `spec.md`, load config caps, create a run-id,
   initialise the memory state file.
1. **Isolate** `[Worktrees]` — create a git worktree on a fresh branch off the demo
   repo's `main`. All actor edits happen here, never in the user's checkout.
2. **Loop** (`for attempt in range(MAX_ITERATIONS)`, also bounded by
   `MAX_WALL_SECONDS`):
   - **A. Actor** `[Sub-agents/maker]` — `codex exec --workspace-write` with the
     actor prompt + spec text + last_error. Codex edits files in the worktree.
   - **B. Enforce** `[Worktrees/safety]` — `git diff --name-only`; if `tests/` or
     `constitution.md` changed, roll those paths back (`git checkout --`), record
     the violation as `last_error`, and continue to the next iteration.
   - **C. Tests** `[Connectors]` — run `pytest` in the worktree. On failure, record
     the output as `last_error` and continue.
   - **D. QA critic** `[Sub-agents/checker]` — `codex exec --read-only` over the diff
     + spec + test results; judges whether acceptance criteria are *genuinely* met
     (boundary values, under-coverage). `fail` → `last_error`, continue.
   - **E. Security critic** `[Sub-agents/checker]` — `codex exec --read-only` over the
     diff + full constitution; clause-by-clause compliance with evidence. `fail`
     → `last_error`, continue.
   - On reaching here, **all gates passed** → break to converge.
   - Every iteration writes attempt #, gate verdicts, last_error, and elapsed time
     to **Memory**.
3. **Converge** — commit the change on the branch and write a **PR artifact**
   (markdown: summary, diff, QA report, security findings). This is the handoff to
   human gate #2 (merge). The loop does **not** auto-merge.
4. **Escalate** — if the iteration or wall-clock cap is hit first, write the final
   state + the reason and stop safely (no infinite loop, no silent failure).

Every step is triggered by "the previous step's code called it" — there is no
magic agent-to-agent handoff. The orchestrator owns the control flow.

## 6. Building-block deep dive

This is the heart of the "explore each component" goal — what each block *is*,
how it shows up here, and (where relevant) what it would become in production.

### 6.1 Automations — `trigger.py`
- **What it is:** the heartbeat that turns a one-off run into a loop, plus
  discovery/triage of work.
- **Here:** a manual CLI entrypoint (`python -m loopengine run --spec … --repo …`)
  that ingests `spec.md`, sets the safety caps, and kicks `run_loop`. It also owns
  `MAX_ITERATIONS` / `MAX_WALL_SECONDS` — the agent has no say over these.
- **In production:** the Kanban card-move (Backlog→Dev) fires this via a connector;
  a scheduler could batch-run new specs. The module's interface is designed so the
  trigger source is swappable without touching the loop.

### 6.2 Worktrees — `isolation.py`
- **What it is:** isolated checkouts so parallel agents don't collide, and a clean
  surface to diff/verify what an agent changed.
- **Here:** one `git worktree` per run on a fresh branch. Also houses the
  **read-only-tests enforcement**: because we can't see inside a Codex turn, we let
  it write, then verify on disk with `git diff` and roll back any forbidden path.
  This "detect-and-revert tampering" is itself a concrete, demoable anti-reward-
  hacking control.
- **Interface:** `create(repo) -> worktree_path, branch`; `assert_no_protected_changes(worktree) -> (ok, reason)`;
  `cleanup(worktree)`.

### 6.3 Skills — `skills/`
- **What it is:** project knowledge written down once so the agent stops re-guessing
  conventions every session (the cure for "intent debt").
- **Here:** `constitution.md` (the versioned safety/compliance rule set, §1–§5),
  the three prompt files, and an `AGENTS.md` that tells Codex the house rules
  ("never modify tests or the constitution", output contracts, etc.). Adding one
  clause to the constitution extends the safety net to all future changes.
- **Key property:** read-only to the actor; it is *context and target*, not
  something the actor may edit.

### 6.4 Connectors — `connectors.py`
- **What it is:** the wiring that lets the loop touch real systems.
- **Here, deliberately minimal:** `run_tests()` (pytest → pass/fail + output),
  `write_pr_artifact()` (the local PR stand-in), and git helpers (commit, diff).
- **Safety design:** the safety-critical connectors (running tests, opening the
  "PR") are **ours and are never exposed for the agent to call** — the agent cannot
  certify itself. In production this is where the GitHub/CI/Slack connectors land.

### 6.5 Sub-agents — `agents.py`
- **What it is:** splitting the one who writes from the one who checks; a model
  grades its own homework too generously.
- **Here:** an `Agent` seam with three backends (Mock/Claude/Codex, see §3a), each
  exposing the same three calls with the maker/checker split:
  - `actor` — write-enabled, implements the spec by editing the worktree.
  - `qa_critic` — read-only, judges acceptance beyond "tests are green".
  - `security_critic` — read-only, clause-by-clause constitution audit.
- **Why read-only matters:** the checker is denied edit tools entirely (Codex
  `--sandbox read-only`; Claude no `Edit`/`Write` in `--allowedTools`) — a *hard*
  guarantee it can't edit code to make itself pass, stronger than a prompt
  instruction. The critics also receive the diff inline, so they need no file tools
  at all.
- **Output contract:** each critic returns strict JSON (`verdict` + findings); the
  orchestrator parses the last JSON line of the Codex event stream.

### 6.6 Memory — `memory.py`
- **What it is:** durable state outside any single conversation. "The agent forgets,
  the repo doesn't."
- **Here:** a per-run state file (`runs/<run-id>/state.json`) updated every
  iteration with attempt #, elapsed time, each gate's verdict, and `last_error`.
- **Why it's the spine:** it makes "done" auditable, lets a crashed run be inspected
  or resumed, and carries `last_error` forward so the actor fixes the *root cause*
  rather than restarting cold.

## 7. Data contracts

### 7.1 Input — `spec.md`
Markdown produced upstream by a spec-kit/spec-it plugin. Treated as opaque text and
injected into the actor/critic prompts. Expected to contain: a summary, testable
acceptance criteria, and (ideally) references to applicable constitution clauses.
If clause references are absent, the security critic checks the full constitution.

### 7.2 Memory — `state.json` (shape)
```json
{
  "run_id": "…", "spec_path": "…", "repo": "…", "branch": "…",
  "started_at": "…", "caps": {"max_iterations": 6, "max_wall_seconds": 1200},
  "status": "running | converged | escalated",
  "iterations": [
    {"n": 1, "elapsed_s": 0,
     "enforce": {"ok": true},
     "tests": {"passed": false, "summary": "…"},
     "qa": null, "security": null,
     "last_error": "Tests failed: …"}
  ],
  "result": {"outcome": "…", "artifact": "runs/<id>/pr-artifact.md"}
}
```

### 7.3 Critic output (both QA and Security)
Strict JSON, no markdown fences:
```json
{"verdict": "pass" | "fail", "findings": [ … ]}
```
(QA uses `gaps`, Security uses `findings` with clause + status + evidence — carried
over from the existing prompt files.)

## 8. Safety mechanisms ↔ risks

| Risk | Mechanism in the loop |
|---|---|
| Reward hacking (edit tests to pass) | Tests + constitution are read-only to the actor; `git diff` detects and reverts any protected-path change after the turn. |
| Critic self-certification | Critics run in a `read-only` sandbox — cannot edit any file. |
| Runaway / infinite loop | `MAX_ITERATIONS` + `MAX_WALL_SECONDS`, owned by our loop; escalate on cap. |
| LLM subjective misjudgment | Deterministic pytest gate runs *before* any LLM critic. |
| Silent compliance violation | Security critic checks every applicable clause with cited evidence. |
| Bad auto-merge | No auto-merge; convergence only produces a PR artifact for human review. |
| Changing rules | Constitution is a version-controlled file; one new clause covers all future runs. |

## 9. Demo scenario

Reuse the SecondBrain worked example: **daily cumulative transfer-limit validation.**
- `demo/bankapp/transfer.py` — a transfer function missing the limit check (and,
  for the security-critic beat, an intermediate amount stored as `float` to violate
  §1 on a naive first pass).
- `demo/bankapp/tests/test_transfer.py` — acceptance tests including the exact-equal
  boundary case (so a sloppy `>` vs `>=` first attempt fails and forces an iteration).
- `demo/bankapp/specs/transfer-limit.md` — the input spec.
- Expected narrative: attempt 1 fails the boundary test → attempt 2 passes tests but
  the security critic flags the `float` §1 violation → attempt 3 converges → PR
  artifact written.

## 10. Run UX

```
python -m loopengine run \
  --spec demo/bankapp/specs/transfer-limit.md \
  --repo demo/bankapp
```
Streams stage-by-stage progress; on success prints the path to the PR artifact and
the final state file; on cap prints the escalation reason.

## 11. Testing strategy for the prototype itself

- Block modules are unit-testable in isolation with the **`MockAgent`** double, so
  the loop's control flow, enforcement, and memory are tested **without any live
  agent** (fast, offline, deterministic CI — runs on the dev machine and the work
  machine alike).
- One end-to-end test runs the full loop against the demo repo with `MockAgent`
  scripted to reproduce the 3-attempt narrative (boundary fail → §1 float catch →
  converge) and a second to exercise escalate-on-cap.
- **Live verification on the dev machine:** an *opt-in* test (skipped unless
  `LOOP_LIVE=claude`) runs the loop once with the real `ClaudeAgent` against the demo
  repo, so "every step works with a real agent" is demonstrable here before the Codex
  demo. It costs tokens + needs Claude auth, hence opt-in.
- **Codex parse coverage without Codex:** `CodexAgent`'s output parsing is unit-tested
  against `tests/fixtures/codex_events.jsonl` — a *real* sample captured by
  `scripts/codex_smoke.py` on the work machine — so the one piece we can't run here is
  still tested against real data.

## 11a. Iteration strategy trade-off (decided: favor correctness)

When any gate (`B` enforce, `C` tests, `D` QA, `E` security) fails, the iteration
records the reason as `last_error`, writes it to Memory, and loops back to the
**Actor** — the gates are ordered and short-circuit, so a failure at `C` skips `D`
and `E` that iteration (cheap/deterministic gates run before expensive/subjective
ones).

There are two ways the Actor can recover on the next attempt:

| Strategy | What it does | Trade-off |
|---|---|---|
| **Full re-attempt with feedback** (chosen) | Actor re-derives the implementation from the spec, now carrying the specific `last_error`. Prompt instructs it to fix the **root cause, not the symptom**. | Higher token cost per failure; strongest correctness — discourages symptom-patching and lets the actor reconsider its whole approach. |
| Incremental edits | Actor makes a minimal patch on the existing worktree state targeting only the failing gate. | Cheaper; but more prone to band-aid fixes that pass one gate while degrading overall design. |

**Decision: favor correctness — full re-attempt with feedback.** Token cost is
accepted as the price of root-cause fixes. The bounded loop (`MAX_ITERATIONS` /
`MAX_WALL_SECONDS`) caps the worst-case cost; on cap the run escalates to a human
with the last recorded `last_error`. (The incremental strategy is noted as a future
lever if token cost becomes a constraint.)

## 12. Open questions / risks

- **Codex `--json` event schema:** the exact shape of the final event we parse for
  critic JSON must be verified against the installed Codex version before relying on
  `_last_json_line`. (Reference impl flags the same caveat.)
- **Read-only sandbox + JSON output:** confirm `codex exec --sandbox read-only`
  reliably emits a final JSON message we can parse for the critics.
- **Worktree on the demo repo:** `demo/bankapp` must be its own initialised git repo
  for worktrees to work; the prototype should init it on first run if absent.
- **Spec clause references:** if `spec.md` doesn't name applicable clauses, the
  security critic checks all of them — slightly more tokens, simpler contract.

## 13. The honest caveats (from the Loop Engineering notes)

This prototype is a loop you can *walk away from for one feature* — not a license to
stop reviewing. The three problems that get sharper, not softer, as the loop
improves:
- **Verification stays on you** — the PR artifact's "done" is a claim, not a proof;
  the human merge gate is non-negotiable.
- **Comprehension debt** — read what the loop produced; the demo artifact is meant
  to be read, not rubber-stamped.
- **Cognitive surrender** — the loop is a tool for work you understand, not a way to
  avoid understanding it.
