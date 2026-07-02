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
- **Tests ship with the feature**: the gate commit is the parent of the
  implementation commit, so merging the loop branch adds both. The generated
  acceptance tests join the permanent suite — and because phase C runs the whole
  suite and `tests/` is protected, every later run must keep prior features green.
  The suite compounds run over run without a human writing a test.

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
- Suite-hygiene / dedup passes over accumulated generated tests. The human merge
  review is the backstop this iteration; a periodic cleanup pass is future work.
- Non-pytest gate runners. `connectors.run_tests` stays pytest, so specs must
  target a Python-runnable gate; a per-repo test command is future work.

## 3. Constraints & key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Who authors C's tests | A `test_author` **agent**, not the actor, not a human | Independence from the maker is the safety property; the human approves the spec upstream. |
| When | **Once, before the loop**, committed onto a dedicated `gate/<run-id>` branch | The actor's worktree branches from the gate commit, so the gate is present and frozen from iteration 1 — and the target repo's `main` is never touched. |
| Where tests land | `tests/` (already in `PROTECTED`) | Frozen + read-only to the actor via the existing phase-B guard; no config change. |
| Test-author write scope | May write **only** under `tests/`; anything else is reverted | Symmetric inverse of the actor's rule — the gate author must not implement the feature. |
| Baseline rule (two-sided) | On the untouched repo: the **existing suite stays green** AND **≥1 NEW test fails** | All-green new tests = vacuous/misread gate; a red existing test = the generated gate contradicts the current suite. Either way: **failed attempt → feedback + retry**, escalate at the cap. |
| AC coverage rule | Every `AC-N` in the spec maps to ≥1 generated test (by test name / marker) | Vacuity alone is weak — one honest red test could carry five vacuous ones. Mechanical check, no LLM. |
| Determinism rule | The baseline run executes **twice**; results must be identical | A flaky gate breaks the loop's core assumption; cheap because acceptance tests are fast. |
| Language & layout | Layered context: spec **"Stack & interface"** section → target-repo conventions file (`AGENTS.md`/`CLAUDE.md`) → existing code; the frozen gate then pins the actor mechanically | Both CLIs read conventions files natively from the worktree cwd — zero engine code. Greenfield repos must pin the stack in the spec and ship a conventions file. See §6a. |
| Generated tests' home | `tests/acceptance/test_<feature-slug>.py` | Provenance visible, grouped per feature, still under protected `tests/`. |
| Tests after merge | Gate tests merge with the implementation (gate commit is the implementation commit's parent) | The acceptance suite compounds; phase C runs the whole suite, so prior features are regression-protected for free. |
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
│  0d. Verify on the UNTOUCHED code (baseline run):         │
│         · vacuity — ≥1 NEW test red · old tests green     │
│         · AC coverage — every AC-N maps to ≥1 test        │
│         · determinism — run twice, identical results      │
│         └ any miss → failed attempt → feedback + retry    │
│  0e. Freeze: commit the gate onto gate/<run-id>           │
└─────────────────────────────────────────────────────────┘
        │  (actor worktree branches from the gate commit;
        │   gate read-only to the actor via phase B)
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
  reporter) -> GateResult`. Owns Phase 0: the author→enforce→collect→verify→freeze
  sequence and its bounded retry. Verify = vacuity + AC coverage + determinism
  (double baseline run). Returns the gate ref (branch/commit) on success or an
  escalation reason. Kept out of `orchestrator.py` so the loop stays thin.
  AC coverage is mechanical: extract `AC-N` ids from the spec, match them against
  generated test names/comments (`ac1` / `AC-1`); any unmapped AC → retry feedback.
- **`connectors.py`** — reuse `run_tests`; add a small helper to detect
  *collection* errors vs. *assertion* failures (pytest exit code 2/5 vs 1) so
  0c and 0d can tell "won't import" from "fails as expected".
- **`orchestrator.py` / `connectors.git_diff`** — thread a `base` ref (default
  `"main"`) through `run_loop` so the QA/security diff and the PR artifact compare
  against the **gate commit**, not `main`. The PR diff stays implementation-only;
  the artifact additionally lists the gate's test files so the human reviewer sees
  both what changed and what it was graded against.
- **`skills/prompts/qa_critic.txt`** — one added instruction: *also flag when the
  test suite itself misses or contradicts an acceptance criterion*. The QA critic
  already re-reads the spec, making it a third independent interpretation — a
  false convergence now requires author, actor, AND QA to misread the same way.
- **`isolation.py`** — reuse `assert_no_protected_changes`; add the inverse guard
  `assert_only_paths(worktree, ("tests/",))` for the test-author turn (0b).
- **`config.py`** — add `GATE_MAX_ATTEMPTS = 3`. `PROTECTED` gains the repo
  conventions files (`AGENTS.md`, `CLAUDE.md`) so the actor cannot rewrite the
  conventions it is graded under. `tests/` already covers the generated gate.
- **`trigger.py`** — `--gate {provided,synthesize}` flag; when `synthesize`, call
  `gate.synthesize_gate()` before `run_loop()`; on gate escalation, finish the run
  as `escalated` without entering the loop.
- **`reporter.py`** — add a `gate(status, detail)` callback; Console prints a
  `G Gate ✓ authored 4 tests (3 red on baseline)` line, Slack posts one reply.
- **`memory.py`** — record the gate outcome in `state` (`"gate": {...}`): attempts,
  test files produced, gate ref (`gate/<run-id>` commit), baseline red/green split,
  AC-coverage map. Keeps the run auditable end to end.

## 6. Data flow & freeze mechanism

1. `trigger.run` (gate=synthesize): `ensure_demo_repo(repo)` → read spec.
2. `gate.synthesize_gate` runs the test-author against `repo` in a scratch
   worktree branched from `main`.
3. On success it **commits the generated `tests/` onto a `gate/<run-id>` branch**
   — the target repo's `main` is never touched.
4. `run_loop` then creates the actor worktree **branched from the gate commit**
   (base ref threaded through), so the actor's worktree contains the frozen gate
   from iteration 1, and any actor edit to it is reverted by phase B.
5. All diffs (QA, security, PR artifact) use the gate commit as base, so the PR
   diff is implementation-only; the artifact lists the gate's test files alongside.
6. **On human merge of the loop branch, the gate tests land together with the
   implementation** — the acceptance suite for feature N becomes part of the
   permanent, protected `tests/` for feature N+1's run. Nothing extra to build:
   the lineage (gate commit → implementation commit) makes it automatic.

## 6a. How the agents know language & layout

Neither the actor nor the test-author prompt names a programming language.
Resolution is layered context — the first three inform the *test-author*, the
fourth then binds the *actor* mechanically:

1. **Spec — "Stack & interface" section (human-approved intent).** Required for
   greenfield specs: language, test framework, module layout, entry-point
   signature(s). Both agents receive the spec verbatim, so both inherit it.
2. **Target-repo conventions file (`AGENTS.md` / `CLAUDE.md`).** Both backends
   read these natively from their working directory (`codex exec` → `AGENTS.md`,
   `claude -p` → `CLAUDE.md`), and both the actor and the test-author run with
   cwd = a worktree of the target repo — so this reaches them with **zero engine
   code**. It carries the per-repo "how and where": source layout, test directory
   (`tests/acceptance/`), naming, style. Seeded once per repo by a human — that is
   configuration, not coding, the same pattern as the repo-local
   `constitution.md`. Listed in `PROTECTED` so the actor cannot edit its own
   conventions.
3. **Existing code.** In a brownfield repo the module being extended pins language
   and structure by example; the test-author reads real interfaces off disk.
4. **The frozen gate.** Once the tests exist, their imports pin the module path,
   names, signatures, and exception types — the actor cannot converge in the
   wrong language because phase C fails on import until the graded interface
   exists exactly.

The gate runner stays pytest this iteration (`connectors.run_tests`), so specs
must target a Python-runnable gate (note: the website demo's file-parsing tests
are pytest too — the *product* need not be Python, only the gate).

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
- **AC coverage check (0d)** ensures no acceptance criterion is silently dropped —
  a misread-by-omission is caught mechanically, not by luck.
- **Determinism check (0d)** rejects flaky gates before the loop depends on them.
- **QA critic as third reader (D)** re-reads the spec independently and is
  instructed to flag a test suite that misses or contradicts a criterion — a false
  convergence needs the author, the actor, AND the QA critic to misread the same way.
- **Independence** of author and actor already makes a shared misread far less
  likely than an actor grading itself.
- Future levers (not this iteration): examples-style specs (less interpretation),
  optional human gate-review (`--review-gate`).

## 8. Demo scenario (new)

`demo/greenfield-transfer/` (or bankapp with tests removed): a prose spec, an
incomplete `transfer.py`, **no `tests/`**. The repo ships an `AGENTS.md`
conventions file (Python 3 · pytest · `tests/acceptance/` layout) and the spec
carries a **"Stack & interface"** section — together these pin language and
layout before any agent runs (§6a). Run with `--gate synthesize`. The audience
watches:

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
    baseline → all ACs mapped → freeze → committed onto `gate/<run-id>` + protected.
  - vacuity: author writes an all-green test → failed attempt with feedback →
    escalate after `GATE_MAX_ATTEMPTS`.
  - suite contradiction: author writes a test that breaks an *existing* green
    test on baseline → failed attempt; feedback names the broken test.
  - conventions protected: actor edits `AGENTS.md` in the loop → reverted by
    phase B (extend the existing isolation tests).
  - AC coverage: author drops one AC → retry feedback names the missing `AC-N`.
  - determinism: author writes a randomised test (mocked to flip results) →
    detected via double baseline run → failed attempt.
  - bad collection: author writes a syntactically broken/`import`-failing test →
    bounded retry with feedback → escalate after `GATE_MAX_ATTEMPTS`.
  - scope: author also writes a non-tests file → it is reverted; only `tests/`
    survives.
- End-to-end offline: `--gate synthesize` on a copied demo repo, mock test-author
  + mock actor → converges; assert `state["gate"]` recorded (attempts, gate ref,
  red/green split), the loop ran against the generated tests, and the PR artifact
  diff contains the implementation only (gate tests listed, not diffed).
- `reporter` gains a `gate` callback → extend the existing reporter tests.

## 10. Error handling & edge cases

| Case | Behavior |
|---|---|
| Test-author writes no test files | Retry with feedback; escalate after cap. |
| Generated tests don't collect (import/syntax error) | Detected via pytest exit code; retry with the error as feedback; escalate after cap. |
| Vacuous gate (all green on untouched code) | Failed attempt → feedback ("your tests pass on the unimplemented stub — they don't test the new behavior") → retry; escalate after cap. |
| An `AC-N` has no mapped test | Failed attempt → feedback names the uncovered criteria → retry; escalate after cap. |
| Baseline run is nondeterministic (two runs differ) | Failed attempt → feedback → retry; escalate after cap. |
| Generated test fails an *existing* suite member on baseline | Failed attempt → feedback names the contradiction → retry; escalate after cap. |
| Greenfield repo with no conventions file and no Stack section in the spec | Test-author picks the stack implicitly — legal but undesirable; the runbook/spec template requires a Stack & interface section for greenfield. |
| Test-author writes outside `tests/` | Non-`tests/` writes reverted before freeze. |
| `--gate provided` (default) | Skip Phase 0 entirely; current behavior (diff base stays `main`). |
| Gate escalates | Run ends `escalated` with reason `gate:<why>`; no loop, no artifact, `main` untouched. |

## 11. Open decisions (confirm before planning)

1. **New demo repo vs. strip bankapp's tests.** Recommend a *new* `demo/greenfield-
   transfer/` so bankapp keeps its human-test scenario for contrast. (Alt: a
   `--gate synthesize` variant that ignores bankapp's committed tests.)
2. **`gate.py` as a new module vs. a function in `trigger.py`.** Recommend a new
   module — Phase 0 has its own retry/verify shape and deserves isolation.
3. **Reporter surface.** Recommend a dedicated `gate(status, detail)` callback
   (clean) over overloading `phase()` with a fake letter.
