# Self-Authored Gate — Review & Improvements (v2)

> Status: review of the shipped feature (plan `2026-07-02-self-authored-gate.md`, all 11 tasks committed; suite green at 71 passed / 1 skipped)
> Date: 2026-07-08
> Diagram: `docs/diagrams/agentic-loop-self-authored-gate-v2.svg` (supersedes `agentic-loop-self-authored-gate.svg`)

## 1. Review verdict

The plan is well-constructed and the implementation matches it: strict TDD per task, fail-closed defaults, offline-testable throughout, `main` never touched, and the intentional deviations were documented. The diagram accurately reflects the shipped flow. The improvements below are the gaps found by cross-checking spec ↔ plan ↔ code ↔ diagram; two were verified empirically against the running code.

## 2. Improvements

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | **Bug** | **AC-coverage substring false positive** (verified by repro): `_uncovered_acs` strips `-`/`_` and does a substring check, so a spec with `AC-1` and `AC-12` treats AC-1 as covered by a test that only mentions `ac12`. | Match with a digit boundary: `re.search(rf"(?i)ac[-_]?{n}(?!\d)", corpus)` per AC instead of `in`. |
| 2 | **Safety gap** | **One honest red test can carry N vacuous ones.** Vacuity is suite-level (≥1 red) and AC coverage is textual — a test may name `AC-4` in a comment yet `assert True`. The spec's §3 rationale names this risk but the mechanical check doesn't close it. | Strengthen the verify step: every `AC-N` must map to **≥1 test that is red on baseline** — match AC ids against `_failing_ids` (test names) rather than the file corpus. Still mechanical, no LLM. |
| 3 | **Dropped requirement** | **QA-critic "third reader" instruction never shipped.** Design §5 and the §7 safety analysis rely on the QA critic flagging a suite that misses or contradicts an acceptance criterion; `skills/prompts/qa_critic.txt` was never updated and the plan had no task for it — a mitigation the docs claim exists, doesn't. | Add the one instruction to `qa_critic.txt` ("also flag when the test suite itself misses or contradicts an acceptance criterion") + a prompt-content test, mirroring `test_test_author_prompt_loads_with_placeholders`. |
| 4 | **Unbounded phase** | **Phase 0 has no wall-clock budget.** `MAX_WALL_SECONDS` (20 min) governs only the loop; gate synthesis can legally burn 3 × 900 s of agent timeouts (~45 min) before the loop starts. | Start the run clock before `synthesize_gate` and pass a deadline in (or add `GATE_MAX_WALL_SECONDS`); exceeding it is a failed gate → escalate. Cap is config-owned, like `GATE_MAX_ATTEMPTS`. |
| 5 | **Hygiene** | **`gate/<run-id>` branch leaks on failure.** The branch is created by `worktree add -b`; on escalation the worktree is removed but the branch survives, pointing at `main`. | In the failure path, delete the branch after `cleanup_worktree` (`git branch -D gate/<run-id>`); keep it on success — it is the actor's base ref. |
| 6 | **Review UX** | **PR artifact omits what the change was graded against.** Design §6.5 wanted the artifact to list the gate's test files; the plan deferred this to memory. The human merge is the final gate — the reviewer shouldn't need to open the run state file. | Extend `write_pr_artifact` with an optional gate section: test files + red-on-baseline count + `gate/<run-id>` ref. |

Minor notes, no change proposed: the determinism check compares failing ids only (a pass↔skip flip is invisible) — acceptable at this cost point; the double baseline run doubles gate-verify cost on slow brownfield suites — worth a config knob only if it hurts in practice.

## 3. Human-readable process flow

What actually happens on a `--gate synthesize` run, in plain language:

1. **A human approves a spec.** The spec says *what* to build — acceptance criteria (`AC-1`, `AC-2`, …) plus, for a fresh repo, the stack and interface. Nobody writes code or tests. This is the only human input until the end.
2. **The run starts (trigger).** The engine reads the spec, sets the budgets (attempts, iterations, wall time), and opens a run journal (memory) that records everything that follows.
3. **A test author writes the exam — Phase 0.** An independent agent (not the one that will implement) reads the spec inside a scratch copy of the repo and writes acceptance tests in the repo's own test framework. It is only allowed to *add new test files*; anything else it writes is automatically reverted.
4. **The engine checks the exam is real.** With no implementation present, the tests must load cleanly, at least one test must fail for *every* acceptance criterion (a test that already passes proves nothing), no existing test may break, and running twice must give identical results. Any miss → the author gets the error as feedback and retries, up to 3 attempts within the phase's time budget.
5. **The exam is frozen.** The validated tests are committed to a dedicated `gate/<run-id>` branch. The repo's `main` is never touched. From here on, no one — human or agent — edits these tests for the rest of the run.
6. **A second agent implements — the actor-critic loop.** The actor works in an isolated worktree branched *from the frozen gate*, so the exam is present from minute one and any attempt to edit it (or the constitution/conventions files) is detected and rolled back. Each iteration: the actor writes code → protected paths are enforced → the engine itself runs the tests (the agent never grades its own work) → a QA critic re-reads the spec and flags misreads, including problems with the test suite itself → a security critic checks the constitution. Any failure is logged to memory and fed back to the actor. Cap: 6 iterations / 20 minutes.
7. **Converge or escalate — a human decides.** If everything passes, the run produces a PR artifact: the implementation-only diff plus the list of gate tests it was graded against, awaiting **human merge** (the second and final human gate). If no valid gate could be synthesized or a cap was hit, the run stops safely — escalated, loop never entered, `main` untouched, gate branch cleaned up.

The safety story in one line: **the human owns intent (spec approval + merge), one agent writes the exam, a different agent takes it, and only deterministic machinery grades it.**

## 4. Suggested task order (if implemented as a v2 plan)

1. Fix #1 (AC boundary match) — smallest, pure bug, test first with the AC-1/AC-12 repro.
2. #2 (AC↔red mapping) — builds on #1's tests; supersedes the textual corpus check.
3. #3 (QA-critic prompt) — one file + one test.
4. #5 (branch cleanup) — extend the escalation tests to assert the branch is gone.
5. #4 (gate wall budget) — config + `synthesize_gate` deadline param + fake-clock test.
6. #6 (artifact gate section) — extend `write_pr_artifact` + e2e assertion.

Each step keeps the suite green; existing tests must not be weakened.
