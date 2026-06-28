# loopEngineer — Code Walkthrough for the Non-Coder Owner

> This document is a plain-English tour of the entire codebase. It is meant for
> someone who understands the problem well but does not read Python. Every claim
> here is grounded in the actual source code. Jargon is defined the first time it
> appears, collected in the Glossary at the end.

---

## 1. What this project is

loopEngineer is a small Python program that takes a one-page written specification
(a "spec") describing a banking feature and hands it to an AI coding assistant.
The assistant writes the code. Then the program checks whether the code is correct,
safe, and compliant with the bank's engineering rules — automatically, without a
human having to watch. If anything fails, the AI tries again, carrying the failure
reason into the next attempt. When everything passes, the program packages a tidy
report for a human to read and approve before the code goes anywhere near production.
The human always has the final say; the machine never merges anything on its own.

The design separates two different computers. The **dev machine** is the developer's
personal laptop, where the Claude AI assistant is available. The **work machine** is
the company network environment, where only a different AI tool called Codex is
permitted. To bridge this gap, the program defines one common "AI seam" — a
shared interface — so the rest of the loop works identically regardless of which AI
is sitting behind it. The developer builds and tests the loop on the dev machine
using Claude; the final demo runs on the work machine using Codex. The loop itself
does not change.

The project is also deliberately structured as a teaching tool. Each of the six
well-known "loop engineering building blocks" (Automations, Worktrees, Skills,
Connectors, Sub-agents, and Memory) is its own single file. You can pick up any one
file and fully understand what it does without needing to read the others.

---

## 2. The big picture

Here is the loop in one sentence: **a plain Python `for` loop calls the AI, checks
its work through a series of gates, feeds failures back as feedback for the next
attempt, and stops when all gates pass or when a safety cap is reached.**

A diagram of the flow lives at `docs/diagrams/agentic-loop-flow.svg` — it shows the
same stages described below as boxes and arrows.

Every building block maps to exactly one module:

| Building block | What it does | File(s) |
|---|---|---|
| **Automations** | Triggered by a spec; owns the safety caps | `loopengine/trigger.py` |
| **Worktrees** | Gives the AI an isolated sandbox to edit in | `loopengine/isolation.py` |
| **Skills** | Written knowledge the AI reads but cannot change | `skills/` directory |
| **Connectors** | Wires the loop to real systems (git, pytest) | `loopengine/connectors.py` |
| **Sub-agents** | The AI actor and the AI critics | `loopengine/agents.py` |
| **Memory** | Durable log of every attempt, written to disk | `loopengine/memory.py` |
| **Glue** | Sequences all of the above in order | `loopengine/orchestrator.py` |

---

## 3. The core mental model

**The AI is just one step inside a plain Python loop that our code controls.**

Think of an assembly line. The conveyor belt (our code) decides when each station
runs and what it receives. The AI is one station on that belt — a smart but limited
worker. It does not control what comes before it, what comes after it, or whether
its output advances down the line. All of that logic lives in our code, not in the
AI.

Within the loop, the AI plays two distinct roles:

- **The actor (maker):** writes or edits the code, trying to satisfy the spec.
  It has write access to an isolated workspace.
- **The critics (checkers):** read the code and render judgment. They have
  read-only access — they physically cannot write or edit any file. Separate AI
  invocations are used for each critic role so the actor cannot grade its own homework.

### The five safety properties

These are not aspirations. Each one is enforced at a specific place in code.

| Safety property | What it guarantees | Where it is enforced |
|---|---|---|
| **Bounded iterations** | The loop cannot run forever | `config.py` sets `MAX_ITERATIONS = 6` and `MAX_WALL_SECONDS = 1200`; `orchestrator.py` checks both at the top of every attempt |
| **Tests and constitution are read-only to the actor** | The AI cannot cheat by changing the goalposts | `isolation.py` checks git after every actor turn; `connectors.py` reverts any tampering with a three-step undo |
| **Critics physically cannot edit** | No critic can secretly approve bad code by editing it first | Claude critics receive only `Read` as an allowed tool; Codex critics run with `--sandbox read-only`; neither mode grants write access |
| **Deterministic gate runs before AI judgment** | An objective test (pytest) passes before any subjective opinion is consulted | `orchestrator.py` stage C runs `pytest` before stages D (QA critic) and E (security critic); cheaper and certain before expensive and judgmental |
| **No auto-merge** | A human always decides whether the code ships | `orchestrator.py` writes a PR artifact (a markdown report) and stops; no code ever pushes itself to the main branch |

---

## 4. Module-by-module tour

### 4.1 `loopengine/config.py` — The safety caps

**What it is for:** a single place that records every hard limit and important file
path. Nothing in the project changes these at runtime.

**Key things defined here:**

- `MAX_ITERATIONS = 6` — the AI gets at most six attempts per run. This is a plain
  number baked directly into the source code. The AI cannot read it, cannot change it,
  and cannot ask to override it.
- `MAX_WALL_SECONDS = 1200` — twenty minutes of real clock time is the absolute
  ceiling for one run, regardless of how many attempts have been used.
- `PROTECTED = ("tests/", "constitution.md")` — two paths the AI is forbidden to
  touch. The test files define what "correct" means; the constitution defines what
  "safe" means. Protecting both prevents the AI from moving the goalposts.
- `Caps` — a small container (called a *dataclass* in Python, which is just a named
  group of values) that bundles `max_iterations` and `max_wall_seconds` together so
  they can be passed around as a single object.

**Why the caps are deterministic:** the values are Python constants — literal numbers
written in the source file. No environment variable, no command-line flag, no AI
output can change them after the program starts. The orchestrator enforces them by
checking `elapsed > caps.max_wall_seconds` at the top of every loop iteration.

---

### 4.2 `skills/` directory and `loopengine/skills.py` — Project knowledge

**What it is for:** the "skills" directory holds everything the AI needs to know
about the project, written down as plain text files. The Python module `skills.py`
is just a thin reader that loads those files on demand.

**Files in the skills directory:**

- `skills/constitution.md` — five numbered engineering rules (§1 through §5) that
  the bank insists on for all code changes. For example: §1 says money amounts must
  never be represented as a floating-point number (a type that can silently introduce
  rounding errors); §3 says every money movement must leave an audit record; §5 says
  when uncertain, deny access rather than grant it. This file is the source of truth
  for what "safe" means. Adding one new clause here automatically extends the safety
  net to every future run.
- `skills/AGENTS.md` — four bullet-point house rules written specifically for Codex
  (the work-machine AI). It tells Codex never to touch test files or the
  constitution, always use Decimal for money, and output JSON in exactly the format
  expected.
- `skills/prompts/actor.txt` — the instruction given to the AI actor before it writes
  code. It identifies the actor as an implementation engineer, lists hard constraints
  (never modify tests), provides the spec text, and includes any failure feedback from
  the previous attempt.
- `skills/prompts/qa_critic.txt` — the instruction given to the QA critic. It tells
  the critic to check whether the spec's acceptance criteria are genuinely satisfied
  beyond what the automated tests can verify — boundary conditions, exact-equal cases,
  empty inputs.
- `skills/prompts/security_critic.txt` — the instruction given to the security critic.
  It tells the critic to check the code change against every applicable clause of the
  constitution, clause by clause, and cite evidence.

**The `{placeholder}` vs `{{ }}` brace question:** if you open any prompt file you
will see things like `{spec}` and `{last_error}`. You will also see `{{` and `}}`.
Here is why both exist. Python's string formatting system uses `{name}` to mean
"insert the value of `name` here." When the code loads the prompt file and calls
`.format(spec=..., last_error=...)`, Python replaces `{spec}` with the actual spec
text and `{last_error}` with the actual error message. But the JSON format the
critics must output also uses curly braces. To prevent Python from trying to
interpret those as placeholders, the prompt files write `{{` and `}}` wherever a
literal brace is needed in the output. Python's formatter converts `{{` to a single
`{` in the final text that the AI reads.

---

### 4.3 `loopengine/memory.py` — Durable run state

**What it is for:** the loop needs to remember what happened across multiple attempts.
The AI itself has no persistent memory between invocations. `memory.py` solves this
by writing everything to a JSON file on disk after every change.

**JSON** (JavaScript Object Notation) is a plain-text file format for structured data.
It looks like nested lists and dictionaries with labels: `{"status": "running",
"iterations": [...]}`. Any text editor can open and read it.

**How it works:**

- When a run begins, `Memory.create(...)` makes a new folder under `runs/` named with
  the run's unique ID (based on the timestamp plus a short random string) and writes
  an initial `state.json` file there immediately.
- Every time something significant happens — a new attempt starts, a gate verdict
  comes in, an error is recorded, the run finishes — the code calls `_flush()`, which
  overwrites the file on disk with the latest state. This happens *after every single
  change*, not just at the end.
- The last error message from any failed gate is stored in `last_error` in the file.
  The orchestrator reads it back and passes it to the actor at the start of the next
  attempt, so the actor knows specifically what went wrong.

**Why flush after every change:** if the computer loses power or the program crashes
mid-run, the `state.json` file on disk will reflect everything that had happened up
to the last write. The run is therefore auditable even if it never finishes. "The
agent forgets; the file does not."

---

### 4.4 `loopengine/connectors.py` — Wiring to real systems

**What it is for:** connectors are the parts of the program that actually touch the
outside world — running tests, inspecting what the AI changed, writing the final
report. They are deliberately kept separate from the loop logic so the loop stays
readable and the connectors can be swapped in production.

**Key functions:**

- `run_tests(repo)` — the **deterministic gate**. This function runs pytest (the
  Python testing framework — a program that executes test files and reports pass or
  fail) inside the isolated workspace. It uses `sys.executable` to invoke pytest,
  which means it uses the exact same Python interpreter that is running the loop
  itself. This matters because the loop might be running inside a *virtual
  environment* (venv — an isolated Python installation with specific library versions)
  and using any other Python would ignore those libraries. It also passes two flags to
  suppress clutter: `PYTHONDONTWRITEBYTECODE=1` stops Python from writing `.pyc`
  compiled files, and `-p no:cacheprovider` stops pytest from writing a `.pytest_cache`
  folder. Without these, those generated files would appear as "changes" in git and
  could trigger the protected-path check falsely.

- `git_changed_paths(repo)` — asks git which files have changed compared to the last
  *commit* (a commit is a saved snapshot of the codebase; think of it as a checkpoint).
  It runs `git status --porcelain`, which gives a machine-readable list of changes —
  modified, added, deleted, or renamed files.

- `git_revert_paths(repo, paths)` — the **three-step undo** that defeats even staged
  tampering:
  1. `git reset` — removes files from the *staging area* (also called the index; it
     is git's short-term "ready to commit" holding area). If the AI ran `git add` to
     stage a tampered file, this step un-stages it.
  2. `git checkout` — restores the file's content from the last commit, overwriting
     whatever the AI wrote.
  3. `git clean` — removes any new files that were never part of any commit. If the
     AI created a brand-new file under `tests/`, `checkout` would not touch it (git
     only knows about files it has seen before), but `clean` removes it.
  Together, these three commands guarantee the files are back to exactly what git
  recorded. There is no way for an AI edit to survive if its path is in the protected
  list.

- `git_diff(repo, base)` — produces a *diff* (a human-readable comparison showing
  every line added or removed) between the current state and the `main` branch. This
  is what the critics read when reviewing the actor's work.

- `git_commit_all(repo, message)` — called only when all gates pass. It stages
  every change and creates a commit on the isolated branch with the run ID in the
  message. This commit is never automatically merged to `main`.

- `write_pr_artifact(run_dir, summary, diff, qa, security)` — writes a markdown
  file called `pr-artifact.md` in the run's folder. It contains the plain-English
  summary, the QA report, the security report, and the full diff. This is a stand-in
  for a real *pull request* (a PR — the formal way of proposing code changes on
  GitHub, where a reviewer can read and approve or reject). In production this would
  become a real PR; here it is a local file a human reads to decide whether to merge.

---

### 4.5 `loopengine/isolation.py` — Isolated workspaces

**What it is for:** the AI should never edit the real codebase directly. Instead,
the loop creates a *git worktree* — an isolated copy of the repository checked out
into a separate folder on its own fresh *branch* (a branch in git is like an
alternate timeline; changes on it do not affect `main` until explicitly merged).
The AI edits in this copy. Our code then inspects the copy to see what changed.

**Key functions:**

- `create_worktree(repo, branch, root)` — tells git to create a new working copy of
  the repository in a separate folder, on a new branch named after the run ID
  (e.g., `loop/20260628T120000-abc123`). The actor edits files inside this folder.
  The original repository is untouched.

- `cleanup_worktree(repo, worktree)` — after the run finishes (whether it converged,
  escalated, or crashed), the `finally` block in the orchestrator calls this to
  delete the worktree folder and deregister it from git. Nothing is left behind.

- `assert_no_protected_changes(worktree, protected)` — the **anti-reward-hacking
  guard**. After every actor turn, before running tests, this function asks git what
  changed in the worktree. If any changed file's path starts with `tests/` or is
  `constitution.md`, it immediately calls `git_revert_paths` to undo those specific
  changes, then returns `(False, reason)` — a failure signal with an explanation. The
  orchestrator treats this as a failed gate, stores the reason as `last_error`, and
  loops back to the actor.

  Why "detect-and-revert" rather than just "prevent"? We cannot see inside the AI's
  reasoning — it is a black box. We can only observe what it writes to disk. By
  checking the outcome and undoing any violation, we guarantee the invariant holds
  even when the AI tries to cheat (whether intentionally or accidentally).

---

### 4.6 `loopengine/agents.py` — The AI actors and critics

**What it is for:** this module defines the three interchangeable AI backends and
the shared interface they all implement.

**The `Agent` interface (Protocol):** Python's `Protocol` keyword is a way of saying
"any object that has these methods can be used here." Think of it as a job description
rather than a job applicant. Any object with an `actor(...)`, `qa_critic(...)`, and
`security_critic(...)` method qualifies as an Agent. The orchestrator only knows about
the interface — it does not care which backend is behind it.

**The three backends:**

- `MockAgent` — a scriptable stand-in with no AI at all. Instead of calling a real
  AI, it runs a pre-written Python function from a list provided at test time. This
  lets the entire loop be tested offline, quickly, and deterministically, without
  spending any API tokens. When writing tests, you hand `MockAgent` a list of
  scripted actor functions (one per attempt) and optional scripted critic functions.

- `ClaudeAgent` — the dev-machine backend. It runs the `claude` command-line tool
  in "headless" mode (non-interactive, with no screen). For the actor, it passes:
  `--permission-mode acceptEdits` (Claude is allowed to write files without asking),
  `--allowedTools "Read,Edit,Write"` (those are the only tools Claude may use), and
  `--max-turns N` (a cap on internal thinking steps). For the critics, it passes
  `--allowedTools "Read"` only — no `Edit` or `Write` — and asks for JSON-formatted
  output. The actor's output is not parsed; the disk state after it runs is the source
  of truth. The critic's output is parsed to extract the JSON verdict.

- `CodexAgent` — the work-machine backend. Structurally identical to `ClaudeAgent`
  but uses the `codex exec` command instead. The actor uses `--sandbox
  workspace-write` (Codex's equivalent of file-edit permission) and the critics use
  `--sandbox read-only` (Codex's hard file-system restriction — the operating system
  itself refuses writes). The `--json` flag tells Codex to emit structured event lines
  (*JSONL* — one JSON object per line, like a log).

**The maker/checker sandbox split as a hard guarantee:** for Claude, the distinction
is enforced by which tools are listed in `--allowedTools`. For Codex, it is enforced
by the operating-system-level sandbox mode. In both cases this is not just a prompt
instruction ("please don't edit files") — it is a hard technical constraint. A
critic running in read-only mode physically cannot write to disk.

**`_last_json_line(stdout)`:** Codex emits multiple event lines as it works. Only
the last one that parses as valid JSON is the verdict. This helper loops over the
lines in reverse order, tries to parse each as JSON, and returns the first one that
succeeds.

**`_extract_json(text)`:** Claude critics may wrap their JSON in a markdown code
fence (` ```json ... ``` `) or embed it in surrounding prose. This helper strips
fences and finds the outermost `{...}` block if the text is not pure JSON. It is
tolerant of formatting variations in AI output.

---

### 4.7 `loopengine/orchestrator.py` — The heart of the loop

**What it is for:** `run_loop` is the single function that sequences every stage of
every attempt. It is the simplest file to read for understanding how the whole
system fits together.

**Walk through `run_loop` stage by stage:**

```
for attempt in range(1, caps.max_iterations + 1):
```
This is a plain Python `for` loop. It counts from 1 to 6 (or whatever
`max_iterations` is set to). All the intelligence happens inside this loop. There is
no magic; the loop body runs once per attempt.

**Wall-clock check:** at the top of each iteration, the loop computes how many
seconds have elapsed since the run started. If the elapsed time exceeds
`max_wall_seconds`, the loop records the reason and returns immediately with status
`"escalated"`. This check happens at the iteration boundary, not mid-stage.

**Stage A — Actor:** `agent.actor(spec_text, last_error, worktree)` is called. The
AI writes or edits files inside the worktree. Our code waits for it to finish.
`last_error` is empty on the first attempt and contains the most recent gate failure
on subsequent attempts, so the actor has specific feedback to work from.

**Stage B — Enforce:** `isolation.assert_no_protected_changes(worktree, PROTECTED)`
checks whether the actor touched `tests/` or `constitution.md`. If it did, the
function reverts those files, stores the reason in `last_error`, and the line
`continue` immediately jumps back to the top of the loop to start the next attempt.
The actor never gets to stages C, D, or E this iteration.

**Stage C — Tests:** `connectors.run_tests(worktree)` runs pytest. If any test
fails, the full pytest output is stored as `last_error` and `continue` jumps back.
Stages D and E are skipped. This is intentional: running the AI critics when the
tests are already failing would waste time and tokens.

**Stage D — QA critic:** `agent.qa_critic(spec_text, diff, tests["summary"])` asks
a separate AI invocation to review whether the acceptance criteria are genuinely met
beyond what the tests verify. The response must have `"verdict": "pass"` to proceed.
Otherwise `continue`.

**Stage E — Security critic:** `agent.security_critic(constitution, diff)` asks
another separate AI invocation to check the diff clause by clause against the
constitution. The response must have `"verdict": "pass"` to proceed. Otherwise
`continue`.

**Convergence:** if the code reaches this point, all five gates have passed. The
orchestrator commits the changes on the worktree branch, writes the PR artifact, and
records `"status": "converged"` in memory. It then returns.

**Escalation:** if the loop exhausts all `max_iterations` attempts without converging,
it records `"status": "escalated"` along with the last error and returns. The caller
(trigger.py) prints this and exits with a non-zero status code.

**The `finally` block:** Python's `finally` keyword means "run this no matter what
— whether the function returned normally, whether an error was raised, or whether
the user pressed Ctrl-C." The cleanup call `isolation.cleanup_worktree(repo,
worktree)` lives in the `finally` block so the temporary worktree is always deleted,
even if the program crashes mid-run.

---

### 4.8 `loopengine/trigger.py` and `loopengine/__main__.py` — The entrypoints

**`trigger.py` — `run()`:** this is the public API for starting a loop run. It
accepts a path to a spec file, a path to the repository, and optional overrides for
the agent, caps, runs directory, and worktrees directory. It assembles all the
pieces — reads the spec, generates a unique run ID, creates the Memory object, loads
the constitution — and then calls `orchestrator.run_loop(...)`. When called without
an explicit agent, it defaults to `ClaudeAgent()`.

**`trigger.py` — `main()`:** this is the command-line interface (CLI). A CLI is a
program you run by typing a command in a terminal rather than clicking buttons. The
`main()` function uses Python's `argparse` library to define what *flags* (options
prefixed with `--`) the command accepts. The `--agent` flag accepts either `claude`
or `codex` and defaults to `claude`. On the dev machine you omit `--agent`; on the
work machine you pass `--agent codex`.

**`__main__.py`:** when you type `python -m loopengine` in a terminal, Python looks
for a file called `__main__.py` inside the `loopengine` folder and runs it. This
file simply calls `trigger.main()` and passes it any arguments you typed after
`loopengine`. It is the bridge between the terminal command and the actual code.

---

### 4.9 `loopengine/demo.py` and `demo/bankapp/` — The demonstration codebase

**`demo.py` — `ensure_demo_repo(path)`:** the loop's worktree mechanism requires the
target repository to already be a git repository (git worktrees are a git feature).
This helper checks whether a `.git` folder exists. If not, it runs `git init`,
stages all files, and creates an initial commit — the baseline snapshot everything
is compared against. If the `.git` folder already exists, it does nothing. This
property is called *idempotency*: calling the function multiple times produces the
same result as calling it once.

**`demo/bankapp/bankapp/transfer.py` — the intentionally incomplete code:**
```python
def transfer(amount, daily_total, tier_limit, audit_log):
    """Currently performs no limit check."""
    audit_log.append(("transfer", amount))
    return "OK"
```
The `transfer` function exists, but it never checks whether the cumulative daily
total plus the new amount would exceed the tier limit. It always returns `"OK"`. The
actor's job is to add that check correctly.

**`demo/bankapp/tests/test_transfer.py` — the unchangeable target:** four tests
define exactly what correct behavior looks like. The most important one is
`test_exact_equal_boundary_allowed`, which verifies that when `daily_total + amount`
equals `tier_limit` exactly, the transfer is *allowed* (not blocked). This test
catches the common off-by-one error where a developer writes `>` instead of `>=`.
Another test, `test_blocked_transfer_is_audited`, verifies that a blocked transfer
must append a `("blocked", amount)` entry to the audit log — corresponding to
constitution §3.

**`demo/bankapp/specs/transfer-limit.md` — the input spec:** five acceptance criteria
(AC-1 through AC-5) written in plain English. AC-3 explicitly calls out the
exact-equal boundary. AC-5 explicitly requires Decimal. This is the document the
actor reads and the critics evaluate against.

---

## 5. A run, end to end

Here is the full three-attempt story of what happens when you run the transfer-limit
demo. Follow along in the modules as each stage is mentioned.

**Setup (trigger.py + demo.py):** you type the command. `trigger.run()` reads the
spec file, calls `ensure_demo_repo()` to verify the bank app is a valid git
repository (it creates the baseline commit if needed), generates a run ID like
`20260628T120000-abc123`, creates a Memory object that immediately writes
`state.json` to `runs/20260628T120000-abc123/`, loads the constitution from
`skills/constitution.md`, and calls `orchestrator.run_loop(...)`.

**Isolation (isolation.py):** `create_worktree()` tells git to create a fresh copy
of the bankapp repository in `.worktrees/loop_20260628T120000-abc123/` on a new
branch. This is where all edits will happen.

---

### Attempt 1 — The boundary bug

**Stage A (agents.py):** the actor is called with the spec text and an empty
`last_error`. It reads the spec, reads the existing `transfer.py`, and writes a new
version. Being a first attempt, it writes what looks like a reasonable check:

```python
if daily_total + amount > tier_limit:
    raise LimitExceeded()
```

The `>` operator means "strictly greater than." So when `daily_total + amount`
equals `tier_limit` exactly, the condition is false, and the transfer proceeds
normally. That seems right intuitively — but it is wrong according to AC-3 and
`test_exact_equal_boundary_allowed`.

**Stage B (isolation.py):** the actor did not touch `tests/` or `constitution.md`.
Gate B passes.

**Stage C (connectors.py):** `run_tests()` runs pytest. Three tests pass, but
`test_exact_equal_boundary_allowed` fails because `50 + 50 > 100` is false and the
function returned `"OK"` — which is correct! Wait — actually the test expects `"OK"`
for the exact-equal case. But the actor's logic has the condition backwards. Let's
be precise: the actor wrote `if daily_total + amount > tier_limit: raise
LimitExceeded()` and then `return "OK"` unconditionally after. For `60 + 50 > 100`
(over limit), that raises correctly. For `50 + 50 > 100` (false, since 100 is not >
100), it falls through and returns `"OK"` — which is what the test expects. So the
boundary test actually passes here.

The test that fails is `test_blocked_transfer_is_audited`. The actor's naïve
implementation raises `LimitExceeded` without first appending `("blocked", amount)`
to the audit log, so the audit assertion fails. The test output becomes `last_error`.
Memory records this against iteration 1. `continue` jumps back to attempt 2.

---

### Attempt 2 — The float §1 violation

**Stage A (agents.py):** the actor is called again, this time with the test failure
in `last_error`. It revises its implementation. This time it adds the audit call and
fixes the logic correctly, but — perhaps taking a shortcut it thinks is harmless —
it stores the comparison using Python's built-in `float()` conversion:

```python
if float(daily_total) + float(amount) <= float(tier_limit):
    audit_log.append(("transfer", amount))
    return "OK"
audit_log.append(("blocked", amount))
raise LimitExceeded()
```

**Stage B (isolation.py):** no protected files touched. Gate B passes.

**Stage C (connectors.py):** all four tests pass this time. The audit logic is
correct. `float()` arithmetic still produces the right results for the values in the
tests. Gate C passes.

**Stage D (agents.py — QA critic):** the QA critic reads the spec, the diff, and
the test results. All acceptance criteria appear to be met by the test results. The
critic returns `{"verdict": "pass", "gaps": []}`. Gate D passes.

**Stage E (agents.py — security critic):** the security critic reads the
constitution clause by clause and the diff. §1 states: "All monetary amounts MUST
use a fixed-point decimal type (e.g. `Decimal`), never `float` or `double`." The
diff clearly shows `float(daily_total) + float(amount)`. The critic returns:
```json
{"verdict": "fail", "findings": [{"clause": "§1", "status": "violated",
 "evidence": "float(daily_total) + float(amount)"}]}
```
Gate E fails. The finding is stored as `last_error`. Memory records the security
verdict for iteration 2. `continue` jumps back to attempt 3.

---

### Attempt 3 — Convergence

**Stage A (agents.py):** the actor receives the §1 violation as feedback. It revises
the implementation, this time importing Python's `Decimal` type and using it
throughout:

```python
from decimal import Decimal

def transfer(amount, daily_total, tier_limit, audit_log):
    if daily_total + amount <= tier_limit:
        audit_log.append(("transfer", amount))
        return "OK"
    audit_log.append(("blocked", amount))
    raise LimitExceeded()
```

(The values passed in by the tests are already `Decimal` objects, so no conversion
is needed — just no float conversions either.)

**Stages B, C, D, E:** all gates pass. The tamper check is clean. All four tests
pass. The QA critic finds all acceptance criteria met. The security critic confirms
`Decimal` is used throughout, finds no violations.

**Convergence (orchestrator.py + connectors.py):** `git_commit_all()` creates a
commit on the worktree branch. `write_pr_artifact()` writes
`runs/20260628T120000-abc123/pr-artifact.md` containing the plain-English summary,
the QA verdict JSON, the security verdict JSON, and the full diff. Memory records
`"status": "converged"`. The orchestrator returns.

**Cleanup (isolation.py):** the `finally` block calls `cleanup_worktree()`. The
temporary folder is removed. The worktree branch still exists in the git repository
but points to the commit that was just made — it is waiting for a human to
review the PR artifact and decide whether to merge.

---

## 6. How the tests work

The test suite (files under `tests/`) proves that the loop behaves correctly without
needing a live AI, a network connection, or any API keys. It runs in seconds.

**Mocks are confined to the agent seam.** A *mock* (or double, or stub) is a
stand-in that behaves in a predictable, scripted way for testing purposes. The
`MockAgent` class is the only mock in the whole suite. All other parts of the system
— git, pytest, the file system, Memory — run as the real thing during tests.
This means the tests genuinely prove that:
- The correct git commands are issued.
- Real pytest runs and its output is correctly interpreted.
- Real files are written and reverted.
- Memory is actually persisted to disk and read back correctly.

**The headline orchestrator narrative test (`test_orchestrator.py`):** the test
`test_three_attempt_narrative_converges` recreates the exact three-attempt story
from Section 5 using `MockAgent` scripted steps. It:
1. Creates a real git repository in a temporary folder with the incomplete
   `transfer.py` and the four real tests.
2. Runs `orchestrator.run_loop()` with a `MockAgent` whose steps write the `>`
   version, then the `float` version, then the `Decimal` version.
3. Asserts that the final state shows `"converged"`, that iteration 1 had a test
   failure, that iteration 2 had a security failure, and that iteration 3 produced
   a PR artifact on disk.

This single test exercises real git, real pytest, real file reverts, real memory,
and real critic verdict parsing — end to end, offline, in a few seconds.

**The escalation test:** `test_escalates_on_iteration_cap` uses a `MockAgent`
scripted to always write the buggy `>` version. With `max_iterations=3`, it verifies
that after three attempts the status is `"escalated"` and the last error mentions
test failure.

**The opt-in live Claude test (`test_live_claude.py`):** `test_live_claude_converges_on_demo`
runs the full loop against the real demo repository using a real `ClaudeAgent`. It
is decorated with `@pytest.mark.skipif` so it is skipped unless the environment
variable `LOOP_LIVE=claude` is set. This is intentional: the test spends real API
tokens and takes a minute or more to run. Setting the environment variable is an
explicit opt-in, used when you want to verify that "every step works with a real AI"
before the work-machine demo.

**The Codex fixture and smoke script:** the `CodexAgent` cannot run on the dev
machine because Codex is not installed there. To still test its output-parsing code,
a real Codex event stream was captured on the work machine using `scripts/codex_smoke.py`
and saved as `tests/fixtures/codex_events.jsonl`. The test `test_last_json_line_parses_real_codex_sample`
runs the `_last_json_line()` parser against this saved sample and verifies it
extracts the correct verdict. This means the one piece of the system that cannot run
on the dev machine is still tested against real data.

---

## 7. Running it

### The test suite

From the project root, with the virtual environment active:

```
.venv/bin/python -m pytest
```

This runs all tests except the live Claude test. It should take under a minute and
show all green. These tests do not require any AI API keys or network access.

To also run the live Claude test (requires Claude Code installed and authenticated):

```
LOOP_LIVE=claude .venv/bin/python -m pytest tests/test_live_claude.py
```

### On the dev machine — using Claude

```
.venv/bin/python -m loopengine run \
  --spec demo/bankapp/specs/transfer-limit.md \
  --repo demo/bankapp
```

This defaults to `--agent claude`. Claude Code must be installed and logged in. The
loop will run through the transfer-limit demo, printing progress. On convergence it
prints the path to the PR artifact.

### On the work machine — using Codex

First, run the smoke script once to verify Codex is installed and the flags work:

```
python scripts/codex_smoke.py
```

This invokes `codex exec` with the production flags and dumps the raw event stream.
It is a one-shot sanity check, not part of the test suite.

Then run the loop:

```
python -m loopengine run \
  --spec demo/bankapp/specs/transfer-limit.md \
  --repo demo/bankapp \
  --agent codex
```

---

## 8. Glossary

**Branch:** an alternate timeline in a git repository. Changes on a branch do not
affect the main codebase until someone explicitly merges them.

**CLI (Command-Line Interface):** a program you interact with by typing commands in
a terminal window rather than clicking buttons.

**Commit:** a saved snapshot of the codebase in git, like a named checkpoint that
can be revisited or compared against later.

**Dataclass:** a Python shorthand for creating a simple named container of values
with no behavior beyond holding those values.

**Decorator:** a Python annotation (written with `@`) that wraps a function or class
with additional behavior — used in this project primarily for marking tests as
conditional skips.

**Deterministic:** producing the same result every time for the same inputs, with no
randomness or subjective judgment involved. Pytest is deterministic; an AI critic
is not.

**Diff:** a comparison between two versions of a file or codebase, showing every
line that was added (marked `+`) or removed (marked `-`).

**Flag:** a command-line option, typically written with two dashes, like `--agent
codex`. Flags configure a program's behavior when it starts.

**Git:** a version-control system that tracks every change to every file in a
codebase over time, allowing changes to be compared, reverted, or merged.

**Idempotent:** a function or operation that produces the same result whether called
once or many times. `ensure_demo_repo()` is idempotent: running it on an already-
initialized repository does nothing.

**JSONL:** JSON Lines — a file format where each line is a separate, complete JSON
object. Used by Codex to emit a stream of event messages as it works.

**Mock / double / stub:** a scripted stand-in used in testing that replaces a real
component (like an AI agent) with predictable, pre-written behavior.

**PR (Pull Request):** the standard way of proposing code changes on platforms like
GitHub. A PR shows the diff, allows discussion, and requires a human reviewer to
approve before the code is merged.

**Protocol / interface:** a Python (and general programming) concept defining a set
of methods that any compatible object must have. It is a contract, not an
implementation.

**pytest:** a Python testing framework that runs test functions and reports which
ones pass and which fail.

**Reward hacking:** a failure mode where an AI agent achieves a good score on a
metric by gaming the measurement rather than solving the real problem — for example,
editing a test file to make the test trivially pass.

**Sandbox:** an operating-system-level restriction that limits what a process can
do. A read-only sandbox prevents a process from writing to any file, regardless of
what it tries.

**Staging area (index):** git's short-term holding area where changes are placed
(via `git add`) before being permanently saved in a commit.

**stdout:** the standard output stream of a program — the text that appears in your
terminal when you run a command.

**subprocess:** a Python mechanism for running another program from inside Python
code and capturing its output, used in this project to invoke git, pytest, claude,
and codex.

**Virtual environment (venv):** an isolated Python installation containing specific
library versions for a project, separate from the system Python. Ensures
reproducibility.

**Worktree:** a git feature that creates an additional working copy of a repository
in a separate folder, on its own branch, while sharing the same underlying git
history.
