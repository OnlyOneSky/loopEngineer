# Self-authored acceptance gate — design

> Status: design for review (pre-implementation)
> Date: 2026-07-01
> Project folder: `loopEngineer/`
> Builds on: `2026-06-28-agentic-loop-design.md` (the base loop) and the reporter/
> demo work on branch `claude/cool-roentgen-0a992f`.

## 1. Purpose

Close the gap between the loop's stated purpose — *eliminate the human coding
step* — and how the prototype actually gets its deterministic test gate (phase C).
Today the acceptance tests in `tests/` are **hand-written fixtures**: a human wrote
implementation-grade test code. That reintroduces exactly the coding step the loop
is supposed to remove.

This iteration makes the loop **author its own acceptance gate from the approved
spec**, via an independent `test_author` agent, frozen before the actor runs. The
only human involvement becomes **approving the spec** — intent, not code.

The tension this resolves (from the design dialogue): the gate at C must be
(1) independent of the actor, (2) deterministic and executable, (3) traceable to
intent. "Human-authored" satisfied all three but violated the no-human-coding
goal. Generating the gate from the human-approved spec, by an agent that is *not*
the actor, satisfies all three **and** the no-human-coding goal.

## 2. Goals / non-goals

### Goals
- Add a **gate-synthesis phase** that runs once, before the loop: an independent
  agent turns the approved `spec.md` into concrete pytest acceptance tests.
- **Freeze** the generated tests into the protected path (`tests/`) before the
  actor's first turn, so the actor is graded against tests it did not author and
  cannot edit (phase B still guards them). No-self-certification is preserved.
- Add a **vacuity backstop**: reject a synthesized gate that passes on the
  untouched starting code (a green test before any implementation tests nothing).
- Keep the whole thing **offline-testable** with a scriptable mock, matching the
  repo's existing philosophy.
- Add a **demo scenario** that shows the loop authoring its own gate from a prose
  spec, then implementing against it — a stronger "eliminates the coding step"
  story than pre-baked test files.
- **Backward compatible**: repos that already ship human tests keep working
  unchanged (synthesis is opt-in).

### Non-goals (this iteration)
- A spec DSL / examples-table compiler (the "examples-as-spec" option). Noted as
  future; we do agent-generation + the vacuity backstop now.
- Human *review/approval of the generated tests* (the "approve-tests" option).
  Per the chosen design, the human gate is spec approval only. A future
  `--review-gate` flag is left as a seam, not built.
- Changing the base loop (A–E), the caps, the Slack/reporter work, or the
  maker/checker sandbox model. This sits *in front of* the existing loop.
- Regenerating or amending the gate mid-loop. The gate is synthesized once and
  frozen for the run.

## 3. Constraints & key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Who authors C's tests | A `test_author` **agent**, not the actor, not a human | Independence from the maker is the safety property; the human approves the spec upstream. |
| When | **Once, before the loop**, output committed onto the base branch | The actor's worktree branches from that commit, so the gate is present and frozen from iteration 1. |
| Where tests land | `tests/` (already in `PROTECTED`) | Frozen + read-only to the actor via the existing phase-B guard; no config change. |
| Test-author write scope | May write **only** under `tests/`; anything else is reverted | Symmetric inverse of the actor's rule — the gate author must not implement the feature. |
| Vacuity rule | At least one generated test MUST fail on the untouched repo | A gate that is all-green before implementation is vacuous/misread; fail closed → escalate. |
| Bad-collection handling | Bounded retry with feedback (`GATE_MAX_ATTEMPTS`), then escalate | Mirrors the actor retry loop; a gate that won't even import is not a gate. |
| Opt-in | `--gate {provided,synthesize}` (default `provided`) | Backward compatible; existing demos and human-test repos are unaffected. |
| Offline testing | `MockAgent.test_author` scriptable step | Same double that powers the current suite; no keys/network. |

## 4. Architecture

A new **Phase 0 — Gate synthesis** runs in `trigger.run()` *before*
`orchestrator.run_loop()`, operating on the base repo:

```
spec.md (human-approved)
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 0 — Gate synthesis (new; runs once, bounded)       │
│  0a. test_author agent reads spec (+ code interfaces),   │
│      writes pytest acceptance tests under tests/ only     │
│  0b. Enforce: keep only tests/ writes; revert the rest    │
│  0c. Collect check: tests must import/collect             │
│         └ fail → bounded retry with feedback              │
│  0d. Vacuity check: run on UNTOUCHED code; ≥1 must fail   │
│         └ all green → escalate ("vacuous gate")           │
│  0e. Freeze: commit generated tests onto the base branch  │
└─────────────────────────────────────────────────────────┘
        │  (gate now part of main; read-only to the actor)
        ▼
   orchestrator.run_loop()  →  A → B → C → D → E  (unchanged)
```

The actor never sees the test-author's reasoning — only the frozen test files,
exactly as it sees human tests today. Independence holds at the invocation level
even though one `Agent` object may implement both roles (separate LLM calls,
separate contexts).

## 5. Components (one responsibility each)

- **`skills/prompts/test_author.txt`** (new): instructs the agent to read the
  spec, write pytest acceptance tests covering *every* acceptance criterion incl.
  boundaries, import the real interfaces, be deterministic, **fail on unimplemented
  code**, write only under `tests/`, and NOT implement the feature.
- **`agents.py`** — add `test_author(spec, worktree, last_error) -> None` to the
  `Agent` protocol.
  - `ClaudeAgent`/`CodexAgent`: a write-capable invocation scoped to tests
    (`--allowedTools Read,Edit,Write` / `--sandbox workspace-write`), separate
    from the actor call.
  - `MockAgent`: `test_author_steps` list, scriptable like `actor_steps`.
- **`gate.py`** (new module): `synthesize_gate(spec_text, repo, agent, caps,
  reporter) -> GateResult`. Owns Phase 0: the author→enforce→collect→vacuity→freeze
  sequence and its bounded retry. Returns success (gate frozen) or an escalation
  reason. Kept out of `orchestrator.py` so the loop stays thin.
- **`connectors.py`** — reuse `run_tests`; add a small helper to detect
  *collection* errors vs. *assertion* failures (pytest exit code 2/5 vs 1) so
  0c and 0d can tell "won't import" from "fails as expected".
- **`isolation.py`** — reuse `assert_no_protected_changes`; add the inverse guard
  `assert_only_paths(worktree, ("tests/",))` for the test-author turn (0b).
- **`config.py`** — add `GATE_MAX_ATTEMPTS = 3`. `PROTECTED` unchanged.
- **`trigger.py`** — `--gate {provided,synthesize}` flag; when `synthesize`, call
  `gate.synthesize_gate()` before `run_loop()`; on gate escalation, finish the run
  as `escalated` without entering the loop.
- **`reporter.py`** — add a `gate(status, detail)` callback; Console prints a
  `G Gate ✓ authored 4 tests (3 red on baseline)` line, Slack posts one reply.
- **`memory.py`** — record the gate outcome in `state` (`"gate": {...}`): attempts,
  test files produced, vacuity result. Keeps the run auditable end to end.

## 6. Data flow & freeze mechanism

1. `trigger.run` (gate=synthesize): `ensure_demo_repo(repo)` → read spec.
2. `gate.synthesize_gate` runs the test-author against `repo` (base), in a scratch
   worktree branched from main.
3. On success it **commits the generated `tests/` onto `main`** of the base repo.
4. `run_loop` then calls `isolation.create_worktree(repo, branch, root)` which
   branches from `main` — so the actor's worktree contains the frozen gate from
   iteration 1, and any actor edit to it is reverted by phase B.

> Prototype caveat (documented): gate synthesis commits onto the demo repo's
> `main`. For a real repo you would synthesize onto a feature branch; out of scope
> here, same spirit as the existing "commits onto demo main" behavior.

## 7. Safety analysis

| Property | Preserved? | How |
|---|---|---|
| No self-certification | **Yes** | Test-author ≠ actor invocation; gate frozen + read-only before the actor runs. |
| Deterministic gate | **Yes** | Generated tests are concrete pytest; C is unchanged. |
| Human owns intent | **Yes** | Human approves the spec upstream; the gate is a derivation of that approved contract. |
| Bounded | **Yes** | `GATE_MAX_ATTEMPTS` on synthesis; `MAX_ITERATIONS`/wall cap on the loop. |
| Fail closed | **Yes** | No gate / vacuous gate / un-collectable gate → escalate, never proceed to the loop. |

**Residual risk (named honestly):** the test-author can *misread* the spec, so the
actor is graded against a wrong-but-independent rubric. Mitigations built in:
- **Vacuity check (0d)** catches the most common misreads and any gamed/empty gate
  mechanically — a gate that's green before implementation is rejected.
- **Independence** means a false pass needs the *author* and the *actor* to misread
  the same way — far less likely than an actor grading itself.
- Future levers (not this iteration): examples-style specs (less interpretation),
  optional human gate-review (`--review-gate`).

## 8. Demo scenario (new)

`demo/greenfield-transfer/` (or bankapp with tests removed): a prose spec, an
incomplete `transfer.py`, **no `tests/`**. Run with `--gate synthesize`. The
audience watches:

```
G Gate    ✓  authored 4 acceptance tests · 3 red on baseline (gate is real)
Iteration 1/6
  A Actor    …
  ...
```

Then the normal A–E loop. This is the headline "the loop wrote its own gate, then
its own code, and our deterministic check still held" story. Added to
`DEMO-RUNBOOK.md` as Scenario 4 (or replacing Scenario 1's framing).

## 9. Testing (offline, deterministic, no keys)

- `gate.py` unit tests with `MockAgent.test_author`:
  - happy path: author writes the known bankapp tests → collect ok → 3 red on
    baseline → freeze → committed onto main + protected.
  - vacuity: author writes an all-green test → escalate `"vacuous gate"`.
  - bad collection: author writes a syntactically broken/`import`-failing test →
    bounded retry with feedback → escalate after `GATE_MAX_ATTEMPTS`.
  - scope: author also writes a non-tests file → it is reverted; only `tests/`
    survives.
- End-to-end offline: `--gate synthesize` on a copied demo repo, mock test-author
  + mock actor → converges; assert `state["gate"]` recorded and the generated
  tests are the ones the loop ran against.
- `reporter` gains a `gate` callback → extend the existing reporter tests.

## 10. Error handling & edge cases

| Case | Behavior |
|---|---|
| Test-author writes no test files | Retry with feedback; escalate after cap. |
| Generated tests don't collect (import/syntax error) | Detected via pytest exit code; retry with the error as feedback; escalate after cap. |
| Vacuous gate (all green on untouched code) | Escalate immediately — do not enter the loop. |
| Test-author writes outside `tests/` | Non-`tests/` writes reverted before freeze. |
| `--gate provided` (default) | Skip Phase 0 entirely; current behavior. |
| Gate escalates | Run ends `escalated` with reason `gate:<why>`; no loop, no artifact. |

## 11. Open decisions (confirm before planning)

1. **New demo repo vs. strip bankapp's tests.** Recommend a *new* `demo/greenfield-
   transfer/` so bankapp keeps its human-test scenario for contrast. (Alt: a
   `--gate synthesize` variant that ignores bankapp's committed tests.)
2. **`gate.py` as a new module vs. a function in `trigger.py`.** Recommend a new
   module — Phase 0 has its own retry/verify shape and deserves isolation.
3. **Reporter surface.** Recommend a dedicated `gate(status, detail)` callback
   (clean) over overloading `phase()` with a fake letter.
