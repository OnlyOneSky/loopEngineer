# Self-Authored Acceptance Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Phase 0 (gate synthesis) to loopEngineer: an independent `test_author` agent turns the human-approved spec into the deterministic acceptance gate, verified on the untouched code and frozen onto a `gate/<run-id>` branch before the actor runs.

**Architecture:** A new `gate.py` module owns the bounded author→enforce→verify→freeze sequence and runs from `trigger.run()` *before* `orchestrator.run_loop()`. The actor's worktree branches off the frozen gate commit (a new `base` ref threaded through the loop), so the actor is graded against tests it did not write and cannot edit. Everything is offline-testable via `MockAgent`.

**Tech Stack:** Python 3.11+ stdlib only, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-01-self-authored-gate-design.md`

## Global Constraints

- All tests run offline with `MockAgent` — no network, no API keys. Run with `.venv/bin/python -m pytest -q` from the repo root.
- Baseline before this plan: **48 passed, 1 skipped**. Every task must leave the whole suite green.
- No new pip dependencies; stdlib + pytest only.
- `GATE_MAX_ATTEMPTS = 3` (config-owned; the agent has no say over caps).
- `PROTECTED` becomes `("tests/", "constitution.md", "AGENTS.md", "CLAUDE.md")`.
- The gate branch is `gate/<run-id>`; the target repo's `main` is never touched by synthesis.
- Phase C contract: run the repo's trusted test command; exit code 0 = pass. Prototype runner: pytest (`sys.executable -m pytest -q -p no:cacheprovider`).
- pytest exit codes used by gate verification: 0 all passed · 1 test failures · 2/3/4 suite-won't-load (interrupted/internal/usage) · 5 no tests collected.
- Commit messages follow the repo's `feat:` / `docs:` / `test:` style and end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Reporter status vocabulary stays `"ok" | "fail" | "info"`.

---

### Task 1: `run_tests` returncode + expanded PROTECTED + `GATE_MAX_ATTEMPTS`

**Files:**
- Modify: `loopengine/config.py`
- Modify: `loopengine/connectors.py` (the `run_tests` return dict)
- Test: `tests/test_connectors.py` (append), `tests/test_isolation.py` (append)

**Interfaces:**
- Consumes: existing `connectors.run_tests(repo) -> dict`, `isolation.assert_no_protected_changes(worktree, protected)`.
- Produces: `run_tests` result gains `"returncode": int` (existing keys unchanged). `config.GATE_MAX_ATTEMPTS = 3`. `config.PROTECTED == ("tests/", "constitution.md", "AGENTS.md", "CLAUDE.md")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_connectors.py`:

```python
def test_run_tests_reports_returncode(tmp_path):
    # exit 5: a repo with no tests at all
    empty = tmp_path / "empty"
    empty.mkdir()
    res = connectors.run_tests(empty)
    assert res["returncode"] == 5 and res["passed"] is False

    # exit 0: one passing test
    ok = tmp_path / "ok"
    (ok / "tests").mkdir(parents=True)
    (ok / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    res = connectors.run_tests(ok)
    assert res["returncode"] == 0 and res["passed"] is True

    # exit 1: one failing test
    bad = tmp_path / "bad"
    (bad / "tests").mkdir(parents=True)
    (bad / "tests" / "test_bad.py").write_text("def test_bad():\n    assert False\n")
    res = connectors.run_tests(bad)
    assert res["returncode"] == 1 and res["passed"] is False
```

(`tests/test_connectors.py` already imports `connectors`; if not, add `from loopengine import connectors` at the top.)

Append to `tests/test_isolation.py` (it already has a git-repo fixture pattern; reuse its helper if one exists, else this is self-contained):

```python
import subprocess
from loopengine import isolation, config


def _mini_repo(tmp_path):
    repo = tmp_path / "mini"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
    (repo / "AGENTS.md").write_text("# conventions\n")
    (repo / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "init"], check=True)
    return repo


def test_conventions_files_are_protected(tmp_path):
    assert "AGENTS.md" in config.PROTECTED and "CLAUDE.md" in config.PROTECTED
    repo = _mini_repo(tmp_path)
    (repo / "AGENTS.md").write_text("# weakened by the actor\n")
    ok, why = isolation.assert_no_protected_changes(repo, config.PROTECTED)
    assert ok is False and "AGENTS.md" in why
    # and the tamper was reverted
    assert (repo / "AGENTS.md").read_text() == "# conventions\n"


def test_gate_max_attempts_exists():
    assert config.GATE_MAX_ATTEMPTS == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_connectors.py tests/test_isolation.py -q`
Expected: FAIL — `KeyError: 'returncode'`, `AssertionError` on PROTECTED, `AttributeError: ... GATE_MAX_ATTEMPTS`.

- [ ] **Step 3: Implement**

In `loopengine/config.py`, change:

```python
MAX_ITERATIONS = 6
MAX_WALL_SECONDS = 1200  # soft cap: checked at each iteration boundary, not mid-stage
GATE_MAX_ATTEMPTS = 3    # phase 0 (gate synthesis) retry cap; owned by our code
PROTECTED = ("tests/", "constitution.md", "AGENTS.md", "CLAUDE.md")
```

In `loopengine/connectors.py`, change the last line of `run_tests` to:

```python
    return {"passed": proc.returncode == 0, "returncode": proc.returncode,
            "summary": proc.stdout + proc.stderr}
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green (51 passed, 1 skipped).

- [ ] **Step 5: Commit**

```bash
git add loopengine/config.py loopengine/connectors.py tests/test_connectors.py tests/test_isolation.py
git commit -m "feat: run_tests returncode, protect conventions files, GATE_MAX_ATTEMPTS

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: isolation — worktree `base` ref + `enforce_author_scope`

**Files:**
- Modify: `loopengine/isolation.py`
- Test: `tests/test_isolation.py` (append)

**Interfaces:**
- Consumes: `connectors.git_revert_paths(repo, paths)`.
- Produces:
  - `isolation.create_worktree(repo: Path, branch: str, root: Path, base: str = "main") -> Path` — new optional `base`; existing callers unchanged.
  - `isolation.enforce_author_scope(worktree: Path, allowed: tuple[str, ...] = ("tests/",)) -> tuple[list[str], list[str]]` — returns `(kept_paths, reverted_paths)`. The test author may only **add new files** under `allowed`; modifications to tracked files anywhere and additions elsewhere are reverted.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_isolation.py` (reuses `_mini_repo` from Task 1):

```python
def test_create_worktree_from_custom_base(tmp_path):
    repo = _mini_repo(tmp_path)
    # make a side branch with an extra file
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "gate/x"], check=True)
    (repo / "tests" / "test_gate_only.py").write_text("def test_g():\n    assert True\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "gate"], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "main"], check=True)

    wt_main = isolation.create_worktree(repo, "loop/a", tmp_path / "w1")
    wt_gate = isolation.create_worktree(repo, "loop/b", tmp_path / "w2", base="gate/x")
    try:
        assert not (wt_main / "tests" / "test_gate_only.py").exists()
        assert (wt_gate / "tests" / "test_gate_only.py").exists()
    finally:
        isolation.cleanup_worktree(repo, wt_main)
        isolation.cleanup_worktree(repo, wt_gate)


def test_enforce_author_scope_keeps_only_new_test_files(tmp_path):
    repo = _mini_repo(tmp_path)
    # the author: adds a new test (OK), adds a nested new test (OK),
    # writes implementation code (NOT OK), and modifies an existing test (NOT OK)
    (repo / "tests" / "acceptance").mkdir()
    (repo / "tests" / "acceptance" / "test_new.py").write_text("def test_n():\n    assert False\n")
    (repo / "app.py").write_text("x = 2\n")
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert False\n")

    kept, reverted = isolation.enforce_author_scope(repo)
    assert kept == ["tests/acceptance/test_new.py"]
    assert set(reverted) == {"app.py", "tests/test_a.py"}
    assert (repo / "app.py").read_text() == "x = 1\n"                     # reverted
    assert "assert True" in (repo / "tests" / "test_a.py").read_text()    # reverted
    assert (repo / "tests" / "acceptance" / "test_new.py").exists()       # kept
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_isolation.py -q`
Expected: FAIL — `TypeError: create_worktree() got an unexpected keyword argument 'base'` and `AttributeError: ... enforce_author_scope`.

- [ ] **Step 3: Implement**

In `loopengine/isolation.py`, change `create_worktree` and add `enforce_author_scope`:

```python
def create_worktree(repo: Path, branch: str, root: Path, base: str = "main") -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    worktree = root / branch.replace("/", "_")
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q",
                    "-b", branch, str(worktree), base], check=True)
    return worktree


def enforce_author_scope(worktree: Path,
                         allowed: tuple[str, ...] = ("tests/",)) -> tuple[list[str], list[str]]:
    """Gate-synthesis counterpart of assert_no_protected_changes: the test
    author may only ADD new files under `allowed`. Modifying any tracked file
    (including existing tests — it must not weaken prior gates) or adding files
    elsewhere is reverted. Uses -uall so untracked files are listed one by one
    (porcelain otherwise collapses a new directory to a single entry).
    Returns (kept_paths, reverted_paths)."""
    out = subprocess.run(["git", "-C", str(worktree), "status", "--porcelain", "-uall"],
                         capture_output=True, text=True).stdout
    kept, reverted = [], []
    for line in out.splitlines():
        if not line.strip():
            continue
        status, entry = line[:2], line[3:]
        paths = entry.split(" -> ") if " -> " in entry else [entry]
        if status == "??" and paths[-1].startswith(allowed):
            kept.append(paths[-1])
        else:
            reverted.extend(paths)
    connectors.git_revert_paths(worktree, reverted)
    return sorted(kept), sorted(set(reverted))
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add loopengine/isolation.py tests/test_isolation.py
git commit -m "feat: worktree base ref + author-scope enforcement (additions-only under tests/)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: memory — record the gate outcome

**Files:**
- Modify: `loopengine/memory.py`
- Test: `tests/test_memory.py` (append)

**Interfaces:**
- Consumes: existing `Memory.create(...)`, `Memory._flush()`.
- Produces: `Memory.record_gate(info: dict) -> None` writing `state["gate"]`; `create()` initialises `"gate": None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_memory.py` (it already imports `Memory` and `Caps`; follow its existing create-call pattern):

```python
def test_record_gate_persists(tmp_path):
    m = Memory.create(tmp_path, "run-g", "spec.md", "repo", "loop/run-g", Caps())
    assert m.state["gate"] is None
    m.record_gate({"ok": True, "ref": "gate/run-g", "tests": ["tests/acceptance/test_x.py"]})
    reloaded = json.loads(m.path.read_text())
    assert reloaded["gate"]["ref"] == "gate/run-g"
```

(Add `import json` at the top of the file if missing.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_memory.py -q`
Expected: FAIL — `KeyError: 'gate'`.

- [ ] **Step 3: Implement**

In `loopengine/memory.py`: inside `create()`, add `"gate": None,` to the `state` dict (after the `"caps"` entry), and add the method:

```python
    def record_gate(self, info: dict) -> None:
        self.state["gate"] = info
        self._flush()
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add loopengine/memory.py tests/test_memory.py
git commit -m "feat: memory records the gate-synthesis outcome

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: reporter — dedicated `gate()` callback

**Files:**
- Modify: `loopengine/reporter.py`
- Test: `tests/test_reporter.py` (append)

**Interfaces:**
- Consumes: existing reporter classes and `_GLYPH`.
- Produces: `gate(status: str, detail: str = "") -> None` on `Reporter` protocol, `NullReporter`, `ConsoleReporter`, `SlackReporter`, `MultiReporter`. Console prints `G Gate     ✓  <detail>`. Slack posts one message; if no run thread exists yet it posts standalone and adopts the ts as thread root.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reporter.py` (reuses its existing `_FakePoster` and `_RecordingReporter`):

```python
def test_console_reporter_gate_line():
    buf = io.StringIO()
    r = ConsoleReporter(out=buf)
    r.gate("info", "synthesizing acceptance gate (attempt 1/3)")
    r.gate("ok", "frozen: 1 test file(s) · 3 red on baseline → gate/run-x")
    r.gate("fail", "vacuous gate")
    out = buf.getvalue()
    assert "G Gate" in out
    assert "•" in out and "✓" in out and "✗" in out
    assert "gate/run-x" in out


def test_slack_reporter_gate_before_run_start_becomes_root():
    poster = _FakePoster()
    r = SlackReporter(poster)
    r.gate("ok", "frozen: 4 tests")
    assert poster.calls[0][1] is None          # posted standalone
    r.iteration_start(1, 6, 0)
    r.retry("tests failed")
    assert poster.calls[1][1] == "ts-1"        # loop replies thread under the gate post


def test_null_and_multi_accept_gate():
    NullReporter().gate("ok", "x")             # no exception = pass
    a, b = _RecordingReporter(), _RecordingReporter()
    MultiReporter([a, b]).gate("ok", "x")
    assert a.events[-1] == "gate" and b.events[-1] == "gate"
```

Also add to the `_RecordingReporter` class in the same file:

```python
    def gate(self, *a, **k): self.events.append("gate")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_reporter.py -q`
Expected: FAIL — `AttributeError: ... gate`.

- [ ] **Step 3: Implement**

In `loopengine/reporter.py`:

Add to the `Reporter` protocol:

```python
    def gate(self, status: str, detail: str = "") -> None: ...
```

Add to `NullReporter`:

```python
    def gate(self, *a, **k) -> None: ...
```

Add to `ConsoleReporter`:

```python
    def gate(self, status, detail="") -> None:
        glyph = _GLYPH.get(status, "•")
        self._p(f"G Gate     {glyph}  {detail}")
```

Add to `SlackReporter`:

```python
    def gate(self, status, detail="") -> None:
        glyph = {"ok": "✅", "fail": "\U0001f6a8"}.get(status, "\U0001f9ea")
        ts = self._poster.post(f"{glyph} *Gate* — {detail}", self._thread_ts)
        if self._thread_ts is None:
            self._thread_ts = ts
```

Add to `MultiReporter`:

```python
    def gate(self, *a, **k) -> None:
        for r in self._reporters:
            r.gate(*a, **k)
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add loopengine/reporter.py tests/test_reporter.py
git commit -m "feat: dedicated gate() reporter callback (console, slack, multi, null)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: agents — `test_author` role + prompt

**Files:**
- Create: `skills/prompts/test_author.txt`
- Modify: `loopengine/agents.py`
- Test: `tests/test_agents.py` (append)

**Interfaces:**
- Consumes: `skills.prompt(name)`.
- Produces: `test_author(spec: str, last_error: str, worktree: Path) -> None` on the `Agent` protocol and all three backends (argument order mirrors `actor`). `MockAgent` gains constructor param `test_author_steps: list[Callable[[Path], None]] | None = None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agents.py`:

```python
from loopengine import skills
from loopengine.agents import MockAgent


def test_test_author_prompt_loads_with_placeholders():
    text = skills.prompt("test_author")
    assert "{spec}" in text and "{last_error}" in text
    assert "tests/acceptance" in text          # the author is told where tests go
    assert "NOT" in text                       # ... and that it must not implement


def test_mock_agent_test_author_steps_pop_in_order(tmp_path):
    calls = []
    agent = MockAgent(actor_steps=[],
                      test_author_steps=[lambda wt: calls.append(("first", wt)),
                                         lambda wt: calls.append(("second", wt))])
    agent.test_author("spec", "", tmp_path)
    agent.test_author("spec", "feedback", tmp_path)
    assert [c[0] for c in calls] == ["first", "second"]
    assert calls[0][1] == tmp_path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_agents.py -q`
Expected: FAIL — `FileNotFoundError` for the prompt, `TypeError` for the unknown constructor arg.

- [ ] **Step 3: Create the prompt**

Create `skills/prompts/test_author.txt`:

```
You are an acceptance-test author. From the specification below, write the
acceptance tests that will GRADE another engineer's implementation. You are
NOT implementing the feature.

HARD CONSTRAINTS — violating these is a critical failure:
- Write tests ONLY as NEW files under tests/acceptance/ (create the directory
  if needed). Do NOT modify any existing file anywhere, including existing
  tests. Do NOT write implementation code.
- Use the repo's own language and test framework: see the specification's
  "Stack & interface" section, the repo conventions file (AGENTS.md or
  CLAUDE.md), and the existing code.
- Cover EVERY acceptance criterion. Reference its id (e.g. AC-1) in the test
  name or a comment so coverage is mechanically checkable.
- Tests MUST be deterministic: no randomness, clocks, network, or ordering
  dependence.
- Tests MUST fail on the current, unimplemented code and pass only when the
  specification is genuinely implemented. A test that already passes today
  verifies nothing.

SPECIFICATION:
{spec}

FEEDBACK FROM THE PREVIOUS ATTEMPT (empty on first attempt):
{last_error}
```

- [ ] **Step 4: Implement the agents**

In `loopengine/agents.py`:

Add to the `Agent` protocol:

```python
    def test_author(self, spec: str, last_error: str, worktree: Path) -> None: ...
```

Add to `CodexAgent`:

```python
    def test_author(self, spec: str, last_error: str, worktree: Path) -> None:
        prompt = skills.prompt("test_author").format(
            spec=spec, last_error=last_error or "(first attempt)")
        subprocess.run(
            ["codex", "exec", "--sandbox", "workspace-write", "--json",
             "--skip-git-repo-check", prompt],
            cwd=worktree, capture_output=True, text=True, timeout=600)
```

Add to `ClaudeAgent`:

```python
    def test_author(self, spec: str, last_error: str, worktree: Path) -> None:
        prompt = skills.prompt("test_author").format(
            spec=spec, last_error=last_error or "(first attempt)")
        subprocess.run(
            ["claude", "-p", prompt,
             "--permission-mode", "acceptEdits",
             "--allowedTools", "Read,Edit,Write",
             "--max-turns", str(self.max_turns)],
            cwd=worktree, capture_output=True, text=True, timeout=900)
```

In `MockAgent`, change `__init__` and add the method:

```python
    def __init__(self, actor_steps: list[Callable[[Path], None]],
                 qa_fn: Callable[[str, str, str], dict] | None = None,
                 security_fn: Callable[[str, str], dict] | None = None,
                 test_author_steps: list[Callable[[Path], None]] | None = None):
        self._steps = list(actor_steps)
        self._author_steps = list(test_author_steps or [])
        self._qa = qa_fn or (lambda spec, diff, ts: {"verdict": "pass", "gaps": []})
        self._sec = security_fn or (lambda con, diff: {"verdict": "pass", "findings": []})

    def test_author(self, spec: str, last_error: str, worktree: Path) -> None:
        self._author_steps.pop(0)(worktree)
```

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add skills/prompts/test_author.txt loopengine/agents.py tests/test_agents.py
git commit -m "feat: test_author agent role (prompt + claude/codex/mock backends)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `gate.py` — synthesize_gate happy path

**Files:**
- Create: `loopengine/gate.py`
- Create: `tests/test_gate.py`

**Interfaces:**
- Consumes: `isolation.create_worktree/cleanup_worktree/enforce_author_scope`, `connectors.run_tests/git_commit_all`, `Memory.record_gate`, `reporter.gate`, `config.GATE_MAX_ATTEMPTS`, `agent.test_author(spec, last_error, worktree)`.
- Produces: `gate.synthesize_gate(spec_text: str, repo: Path, agent, memory: Memory, worktree_root: Path, reporter=None, max_attempts: int = GATE_MAX_ATTEMPTS) -> dict`. Success: `{"ok": True, "ref": "gate/<run-id>", "tests": [paths], "red_on_baseline": [test ids], "attempts": n}`. Failure: `{"ok": False, "reason": str}`. Either way the dict is also written to `memory.state["gate"]`. On success the tests are committed on branch `gate/<run-id>` in the target repo; `main` is untouched.

- [ ] **Step 1: Write the failing happy-path test**

Create `tests/test_gate.py`:

```python
import subprocess
from pathlib import Path

from loopengine import gate
from loopengine.agents import MockAgent
from loopengine.config import Caps
from loopengine.memory import Memory

# A greenfield-style repo: incomplete implementation, NO tests/.
STUB = (
    "from decimal import Decimal\n\n\n"
    "class LimitExceeded(Exception):\n    pass\n\n\n"
    "def transfer(amount, daily_total, tier_limit, audit_log):\n"
    "    raise NotImplementedError\n"
)

SPEC = (
    "# Feature: daily transfer limit\n\n"
    "## Acceptance criteria\n"
    "- AC-1: under-limit transfers return 'OK'.\n"
    "- AC-2: over-limit transfers raise LimitExceeded.\n"
)

GOOD_TESTS = (
    "from decimal import Decimal\n"
    "import pytest\n"
    "from transferapp.transfer import transfer, LimitExceeded\n\n\n"
    "def test_ac1_under_limit_allowed():\n"
    "    assert transfer(Decimal('10'), Decimal('0'), Decimal('100'), []) == 'OK'\n\n\n"
    "def test_ac2_over_limit_blocked():\n"
    "    with pytest.raises(LimitExceeded):\n"
    "        transfer(Decimal('60'), Decimal('50'), Decimal('100'), [])\n"
)


def _greenfield_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "greenfield"
    (repo / "transferapp").mkdir(parents=True)
    (repo / "transferapp" / "__init__.py").write_text("")
    (repo / "transferapp" / "transfer.py").write_text(STUB)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "init"], check=True)
    return repo


def _write_good_tests(wt: Path):
    (wt / "tests" / "acceptance").mkdir(parents=True)
    (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(GOOD_TESTS)


def _mem(tmp_path, repo, run_id="run-g1"):
    return Memory.create(tmp_path / "runs", run_id, "spec.md", str(repo),
                         f"loop/{run_id}", Caps())


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def test_synthesize_gate_happy_path(tmp_path):
    repo = _greenfield_repo(tmp_path)
    main_before = _git(repo, "rev-parse", "main").stdout.strip()
    agent = MockAgent(actor_steps=[], test_author_steps=[_write_good_tests])
    mem = _mem(tmp_path, repo)

    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt")

    assert result["ok"] is True
    assert result["ref"] == "gate/run-g1"
    assert result["tests"] == ["tests/acceptance/test_daily_limit.py"]
    assert len(result["red_on_baseline"]) == 2          # both tests red on the stub
    assert result["attempts"] == 1
    # the gate is committed on its branch, and main is untouched
    show = _git(repo, "show", "gate/run-g1:tests/acceptance/test_daily_limit.py")
    assert "test_ac1_under_limit_allowed" in show.stdout
    assert _git(repo, "rev-parse", "main").stdout.strip() == main_before
    # recorded in memory
    assert mem.state["gate"]["ok"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'loopengine.gate'`.

- [ ] **Step 3: Implement `loopengine/gate.py`**

```python
"""Phase 0 — gate synthesis. An independent test-author agent turns the
human-approved spec into the deterministic acceptance gate, verified on the
UNTOUCHED code and frozen onto a gate/<run-id> branch BEFORE the actor runs.

The maker/checker split extends one layer up: the actor is graded against
tests it did not write and cannot edit. Fail closed: no valid gate -> the run
escalates and the loop never starts. The target repo's main is never touched.
"""
import re
from pathlib import Path

from . import connectors, isolation
from .config import GATE_MAX_ATTEMPTS
from .memory import Memory
from .reporter import NullReporter


def synthesize_gate(spec_text: str, repo: Path, agent, memory: Memory,
                    worktree_root: Path, reporter=None,
                    max_attempts: int = GATE_MAX_ATTEMPTS) -> dict:
    reporter = reporter or NullReporter()
    branch = f"gate/{memory.state['run_id']}"
    worktree = isolation.create_worktree(repo, branch, worktree_root)
    last_error = ""
    try:
        # Precondition: the existing suite must be green on the untouched code
        # (exit 5 = no tests yet, fine for greenfield).
        baseline = connectors.run_tests(worktree)
        if baseline["returncode"] not in (0, 5):
            return _finish(memory, reporter,
                           f"existing suite is red on the untouched repo:\n"
                           f"{baseline['summary'][-800:]}")

        for attempt in range(1, max_attempts + 1):
            reporter.gate("info", f"synthesizing acceptance gate "
                                  f"(attempt {attempt}/{max_attempts})")
            agent.test_author(spec_text, last_error, worktree)
            kept, reverted = isolation.enforce_author_scope(worktree, ("tests/",))
            if reverted:
                reporter.gate("info", f"reverted {len(reverted)} out-of-scope write(s)")

            problem, red = _verify(worktree, spec_text, kept)
            if problem:
                last_error = problem
                reporter.gate("fail", _first(problem))
                continue

            connectors.git_commit_all(
                worktree, f"gate: acceptance tests ({memory.state['run_id']})")
            info = {"ok": True, "ref": branch, "tests": kept,
                    "red_on_baseline": sorted(red), "attempts": attempt}
            memory.record_gate(info)
            reporter.gate("ok", f"frozen: {len(kept)} test file(s) · "
                                f"{len(red)} red on baseline → {branch}")
            return info

        return _finish(memory, reporter,
                       f"no valid gate after {max_attempts} attempts; "
                       f"last: {_first(last_error)}")
    finally:
        isolation.cleanup_worktree(repo, worktree)


def _verify(worktree: Path, spec_text: str,
            new_files: list[str]) -> tuple[str | None, set[str]]:
    """The mechanical gate-on-the-gate. Returns (problem, red_test_ids)."""
    if not new_files:
        return "no new test files were written under tests/", set()
    run1 = connectors.run_tests(worktree)
    if run1["returncode"] in (2, 3, 4):
        return f"the test suite fails to load:\n{run1['summary'][-800:]}", set()
    if run1["returncode"] == 5:
        return "pytest collected no tests from the new files", set()
    run2 = connectors.run_tests(worktree)          # determinism: run twice
    fail1, fail2 = _failing_ids(run1["summary"]), _failing_ids(run2["summary"])
    if fail1 != fail2:
        return ("the gate is nondeterministic: two identical baseline runs "
                f"disagree on {sorted(fail1 ^ fail2)}"), set()
    if not fail1:
        return ("vacuous gate: every test passes on the UNIMPLEMENTED code — "
                "the tests do not exercise the new behavior"), set()
    outside = {t for t in fail1
               if not any(t.startswith(f) for f in new_files)}
    if outside:
        return f"the new tests break the existing suite: {sorted(outside)}", set()
    missing = _uncovered_acs(spec_text, worktree, new_files)
    if missing:
        return "acceptance criteria without a mapped test: " + ", ".join(missing), set()
    return None, fail1


def _failing_ids(summary: str) -> set[str]:
    """Parse 'FAILED tests/x.py::test_y - ...' lines from pytest -q output."""
    ids = set()
    for line in summary.splitlines():
        line = line.strip()
        if line.startswith(("FAILED ", "ERROR ")):
            ids.add(line.split(" ", 2)[1])
    return ids


def _uncovered_acs(spec_text: str, worktree: Path, new_files: list[str]) -> list[str]:
    """Every AC-N in the spec must appear (as ac-n / ac_n / acn, any case) in
    the generated tests' names or comments. Skipped when the spec has no ids."""
    acs = sorted(set(re.findall(r"AC-\d+", spec_text)))
    if not acs:
        return []
    corpus = " ".join((worktree / f).read_text(encoding="utf-8")
                      for f in new_files).lower()
    corpus = corpus.replace("_", "").replace("-", "")
    return [ac for ac in acs if ac.lower().replace("-", "") not in corpus]


def _finish(memory: Memory, reporter, reason: str) -> dict:
    info = {"ok": False, "reason": reason}
    memory.record_gate(info)
    reporter.gate("fail", _first(reason))
    return info


def _first(text: str) -> str:
    text = (text or "").strip()
    return text.splitlines()[0] if text else ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_gate.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the full suite, then commit**

Run: `.venv/bin/python -m pytest -q` — all green.

```bash
git add loopengine/gate.py tests/test_gate.py
git commit -m "feat: gate.py — synthesize the acceptance gate from the spec (happy path)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `gate.py` — failure modes (fail closed)

**Files:**
- Modify: `tests/test_gate.py` (append; implementation should already handle these — this task proves it and fixes anything it flushes out)

**Interfaces:**
- Consumes: everything Task 6 produced (`synthesize_gate`, fixtures `_greenfield_repo`, `_write_good_tests`, `_mem`, `SPEC`, `GOOD_TESTS`).
- Produces: verified failure behavior; no new public interface.

- [ ] **Step 1: Write the failure-mode tests**

Append to `tests/test_gate.py`:

```python
def _write_vacuous_tests(wt: Path):
    (wt / "tests" / "acceptance").mkdir(parents=True, exist_ok=True)
    (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(
        "def test_ac1_nothing():\n    assert True\n\n"
        "def test_ac2_nothing():\n    assert True\n")


def _write_broken_tests(wt: Path):
    (wt / "tests" / "acceptance").mkdir(parents=True, exist_ok=True)
    (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(
        "def test_ac1_broken(:\n    pass\n")          # syntax error


def _write_ac1_only(wt: Path):
    (wt / "tests" / "acceptance").mkdir(parents=True, exist_ok=True)
    (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(
        "from decimal import Decimal\n"
        "from transferapp.transfer import transfer\n\n"
        "def test_ac1_under_limit_allowed():\n"
        "    assert transfer(Decimal('10'), Decimal('0'), Decimal('100'), []) == 'OK'\n")


def _write_flip_test(wt: Path):
    (wt / "tests" / "acceptance").mkdir(parents=True, exist_ok=True)
    (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(
        "from pathlib import Path\n\n"
        "def test_ac1_flip():\n"
        "    m = Path('flip.marker')\n"
        "    existed = m.exists()\n"
        "    m.touch()\n"
        "    assert existed\n\n"                       # run 1 fails, run 2 passes
        "def test_ac2_anchor():\n    assert False\n")


def _write_tests_and_implementation(wt: Path):
    _write_good_tests(wt)
    (wt / "transferapp" / "transfer.py").write_text("SNEAKY = True\n")


def test_vacuous_gate_retries_then_escalates(tmp_path):
    repo = _greenfield_repo(tmp_path)
    agent = MockAgent(actor_steps=[],
                      test_author_steps=[_write_vacuous_tests, _write_vacuous_tests])
    mem = _mem(tmp_path, repo, "run-vac")
    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt",
                                  max_attempts=2)
    assert result["ok"] is False
    assert "vacuous" in result["reason"]
    assert mem.state["gate"]["ok"] is False


def test_unloadable_suite_is_a_failed_attempt(tmp_path):
    repo = _greenfield_repo(tmp_path)
    agent = MockAgent(actor_steps=[],
                      test_author_steps=[_write_broken_tests, _write_good_tests])
    mem = _mem(tmp_path, repo, "run-load")
    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt")
    assert result["ok"] is True and result["attempts"] == 2   # recovered on retry


def test_missing_ac_coverage_names_the_gap(tmp_path):
    repo = _greenfield_repo(tmp_path)
    agent = MockAgent(actor_steps=[], test_author_steps=[_write_ac1_only])
    mem = _mem(tmp_path, repo, "run-ac")
    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt",
                                  max_attempts=1)
    assert result["ok"] is False
    assert "AC-2" in result["reason"]


def test_nondeterministic_gate_is_rejected(tmp_path):
    repo = _greenfield_repo(tmp_path)
    agent = MockAgent(actor_steps=[], test_author_steps=[_write_flip_test])
    mem = _mem(tmp_path, repo, "run-flip")
    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt",
                                  max_attempts=1)
    assert result["ok"] is False
    assert "nondeterministic" in result["reason"]


def test_author_implementation_writes_are_reverted(tmp_path):
    repo = _greenfield_repo(tmp_path)
    agent = MockAgent(actor_steps=[],
                      test_author_steps=[_write_tests_and_implementation])
    mem = _mem(tmp_path, repo, "run-scope")
    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt")
    assert result["ok"] is True                        # tests kept, impl reverted
    show = subprocess.run(["git", "-C", str(repo), "show",
                           "gate/run-scope:transferapp/transfer.py"],
                          capture_output=True, text=True).stdout
    assert "SNEAKY" not in show and "NotImplementedError" in show


def test_red_existing_suite_escalates_before_authoring(tmp_path):
    repo = _greenfield_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_old.py").write_text("def test_old():\n    assert False\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "red suite"], check=True)
    agent = MockAgent(actor_steps=[], test_author_steps=[])   # never called
    mem = _mem(tmp_path, repo, "run-red")
    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt")
    assert result["ok"] is False
    assert "existing suite is red" in result["reason"]
```

- [ ] **Step 2: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_gate.py -q`
Expected: all pass if Task 6's implementation is complete. If any fail, fix `gate.py` — the tests define the contract; do not weaken them. Known subtlety: the flip test needs `_failing_ids` to compare *sets across two runs* (run 1: `{flip, anchor}` fail; run 2: `{anchor}`), which the Task 6 code handles via `fail1 != fail2`.

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_gate.py loopengine/gate.py
git commit -m "test: gate synthesis fail-closed paths (vacuous, AC gap, flaky, scope, red suite)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: orchestrator — thread the `base` ref

**Files:**
- Modify: `loopengine/orchestrator.py`
- Test: `tests/test_orchestrator.py` (append)

**Interfaces:**
- Consumes: `isolation.create_worktree(..., base=...)` from Task 2.
- Produces: `run_loop(spec_text, repo, agent, caps, memory, constitution, worktree_root, reporter=None, base="main") -> dict`. The worktree branches from `base`; both `git_diff` calls (QA/security diff and the PR-artifact diff) use `base`. Existing callers (default `"main"`) unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orchestrator.py`:

```python
def test_run_loop_from_gate_base_keeps_pr_diff_implementation_only(tmp_path):
    repo = _bank_repo(tmp_path)
    # simulate a frozen gate: an extra acceptance test committed on gate/x
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "gate/x"], check=True)
    (repo / "tests" / "test_gate_extra.py").write_text(
        "from decimal import Decimal\n"
        "from bankapp.transfer import transfer\n\n"
        "def test_gate_extra_under_limit():\n"
        "    assert transfer(Decimal('1'), Decimal('0'), Decimal('100'), []) == 'OK'\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "gate"], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "main"], check=True)

    agent = MockAgent(actor_steps=[_write_decimal], security_fn=_security_fn)
    mem = Memory.create(tmp_path / "runs", "run-b", "spec.md", str(repo), "loop/run-b", Caps())
    state = orchestrator.run_loop("spec", repo, agent, Caps(), mem,
                                  "constitution", tmp_path / ".wt", base="gate/x")
    assert state["status"] == "converged"
    artifact = Path(state["result"]["artifact"]).read_text()
    assert "transfer.py" in artifact                   # implementation is in the diff
    assert "test_gate_extra" not in artifact           # the gate tests are NOT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_orchestrator.py -q`
Expected: FAIL — `TypeError: run_loop() got an unexpected keyword argument 'base'`.

- [ ] **Step 3: Implement**

In `loopengine/orchestrator.py`, change the signature and the three call sites:

```python
def run_loop(spec_text: str, repo: Path, agent: Agent, caps: Caps,
             memory: Memory, constitution: str, worktree_root: Path,
             reporter: Reporter | None = None, base: str = "main") -> dict:
```

```python
    worktree = isolation.create_worktree(repo, branch, worktree_root, base)
```

and both diff calls:

```python
            diff = connectors.git_diff(worktree, base)
```

```python
            artifact = connectors.write_pr_artifact(
                memory.run_dir, spec_summary,
                connectors.git_diff(worktree, base), qa, security)
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green (the new test passes; the actor's worktree contained the gate test, and `_write_decimal` satisfies it).

- [ ] **Step 5: Commit**

```bash
git add loopengine/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: run_loop branches and diffs from a base ref (gate commit aware)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: greenfield demo repo

**Files:**
- Create: `demo/greenfield-transfer/AGENTS.md`
- Create: `demo/greenfield-transfer/transferapp/__init__.py` (empty)
- Create: `demo/greenfield-transfer/transferapp/transfer.py`
- Create: `demo/greenfield-transfer/specs/daily-limit.md`
- Test: `tests/test_gate.py` (append one test)

**Interfaces:**
- Consumes: nothing (static demo assets). **Deliberately no `tests/` directory** — the loop authors its own gate.
- Produces: the demo target for `--gate synthesize`. Contract for Task 10's e2e test: `transferapp.transfer.transfer(amount, daily_total, tier_limit, audit_log) -> "OK"` raising `transferapp.transfer.LimitExceeded`; spec ids `AC-1`…`AC-4`.

- [ ] **Step 1: Create the conventions file**

`demo/greenfield-transfer/AGENTS.md`:

```markdown
# Repo conventions (read-only to the coding agent)

- Language: Python 3, stdlib only. Test framework: pytest.
- Source lives in `transferapp/`; acceptance tests live in `tests/acceptance/`.
- Money is `decimal.Decimal`, never float — including intermediate values.
- Every test references the acceptance-criterion id it covers (AC-N) in its
  name or a comment.
- Do not modify existing files when authoring tests; add new files only.
```

- [ ] **Step 2: Create the stub implementation**

`demo/greenfield-transfer/transferapp/__init__.py`: empty file.

`demo/greenfield-transfer/transferapp/transfer.py`:

```python
"""Daily transfer limit — NOT implemented, and this repo has NO tests/.

This is the self-authored-gate demo: the loop first turns the approved spec
into acceptance tests (phase 0, --gate synthesize), freezes them, and only
then implements this function against them."""
from decimal import Decimal


class LimitExceeded(Exception):
    pass


def transfer(amount: Decimal, daily_total: Decimal, tier_limit: Decimal,
             audit_log: list) -> str:
    """Allow or block a transfer against the daily tier limit."""
    raise NotImplementedError
```

- [ ] **Step 3: Create the spec**

`demo/greenfield-transfer/specs/daily-limit.md`:

```markdown
# Feature: daily cumulative transfer-limit validation (greenfield)

## Stack & interface
- Python 3, pytest. Source in `transferapp/`; acceptance tests in
  `tests/acceptance/`.
- Contract: `transferapp.transfer.transfer(amount, daily_total, tier_limit,
  audit_log) -> "OK"`, raising `transferapp.transfer.LimitExceeded` when the
  transfer is blocked. All monetary values are `decimal.Decimal`.

## Summary
Before a transfer, check whether the customer's cumulative daily transfer
amount plus this transfer exceeds their tier limit; if so, block it and audit
the block.

## Acceptance criteria
- AC-1: when daily_total + amount <= tier_limit, the transfer is allowed and
  returns "OK".
- AC-2: when daily_total + amount > tier_limit, LimitExceeded is raised.
- AC-3: the exact-equal case (daily_total + amount == tier_limit) is ALLOWED.
- AC-4: an allowed transfer appends ("transfer", amount) to audit_log; a
  blocked one appends ("blocked", amount) before raising.

## Applicable constitution clauses
§1 (money is Decimal), §3 (money movement is audited), §5 (fail closed).

> There is deliberately no `tests/` directory in this repo: run with
> `--gate synthesize` so the loop authors its own acceptance gate from this
> spec before implementing.
```

- [ ] **Step 4: Write a guard test that the demo stays gate-less and stub-red**

Append to `tests/test_gate.py`:

```python
from loopengine import config


def test_greenfield_demo_shape():
    demo = config.ROOT / "demo" / "greenfield-transfer"
    assert (demo / "AGENTS.md").exists()
    assert (demo / "specs" / "daily-limit.md").exists()
    assert not (demo / "tests").exists()               # the loop authors the gate
    spec = (demo / "specs" / "daily-limit.md").read_text()
    assert "Stack & interface" in spec
    assert all(f"AC-{n}" in spec for n in (1, 2, 3, 4))
    assert "NotImplementedError" in (demo / "transferapp" / "transfer.py").read_text()
```

- [ ] **Step 5: Run the full suite, then commit**

Run: `.venv/bin/python -m pytest -q` — all green.

```bash
git add demo/greenfield-transfer tests/test_gate.py
git commit -m "feat: greenfield-transfer demo repo (spec + conventions, no tests/)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: trigger — `--gate` wiring + offline end-to-end

**Files:**
- Modify: `loopengine/trigger.py`
- Test: `tests/test_trigger.py` (append)

**Interfaces:**
- Consumes: `gate.synthesize_gate(...)` (Task 6), `run_loop(..., base=...)` (Task 8), the greenfield demo (Task 9).
- Produces: `trigger.run(..., gate_mode: str = "provided")`; CLI flag `--gate {provided,synthesize}` (default `provided`). On gate failure the run finishes `escalated` with outcome `gate: <reason>`, the loop never starts (`state["iterations"] == []`), and the demo repo's `main` is untouched.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trigger.py`:

```python
_GREENFIELD_TESTS = (
    "from decimal import Decimal\n"
    "import pytest\n"
    "from transferapp.transfer import transfer, LimitExceeded\n\n\n"
    "def test_ac1_under_limit_allowed():\n"
    "    assert transfer(Decimal('10'), Decimal('0'), Decimal('100'), []) == 'OK'\n\n\n"
    "def test_ac2_over_limit_blocked():\n"
    "    with pytest.raises(LimitExceeded):\n"
    "        transfer(Decimal('60'), Decimal('50'), Decimal('100'), [])\n\n\n"
    "def test_ac3_exact_equal_allowed():\n"
    "    assert transfer(Decimal('50'), Decimal('50'), Decimal('100'), []) == 'OK'\n\n\n"
    "def test_ac4_audit_trail():\n"
    "    log = []\n"
    "    with pytest.raises(LimitExceeded):\n"
    "        transfer(Decimal('60'), Decimal('50'), Decimal('100'), log)\n"
    "    assert ('blocked', Decimal('60')) in log\n"
)


def _author_greenfield(wt: Path):
    (wt / "tests" / "acceptance").mkdir(parents=True)
    (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(_GREENFIELD_TESTS)


def _implement_greenfield(wt: Path):
    (wt / "transferapp" / "transfer.py").write_text(
        "from decimal import Decimal\n\n\n"
        "class LimitExceeded(Exception):\n    pass\n\n\n"
        "def transfer(amount, daily_total, tier_limit, audit_log):\n"
        "    if daily_total + amount <= tier_limit:\n"
        "        audit_log.append(('transfer', amount)); return 'OK'\n"
        "    audit_log.append(('blocked', amount)); raise LimitExceeded()\n")


def test_synthesize_end_to_end_converges(tmp_path):
    demo_src = config.ROOT / "demo" / "greenfield-transfer"
    repo = tmp_path / "greenfield"
    shutil.copytree(demo_src, repo)
    agent = MockAgent(actor_steps=[_implement_greenfield],
                      test_author_steps=[_author_greenfield])
    state = trigger.run(demo_src / "specs" / "daily-limit.md", repo,
                        agent=agent, caps=Caps(), gate_mode="synthesize",
                        runs_dir=tmp_path / "runs", worktree_root=tmp_path / ".wt")
    assert state["status"] == "converged"
    assert state["gate"]["ok"] is True
    assert state["gate"]["ref"].startswith("gate/")
    # the PR diff is implementation-only: gate tests are listed in memory,
    # not diffed in the artifact
    artifact = Path(state["result"]["artifact"]).read_text()
    assert "transfer.py" in artifact
    assert "test_daily_limit" not in artifact


def test_synthesize_gate_failure_escalates_without_looping(tmp_path):
    demo_src = config.ROOT / "demo" / "greenfield-transfer"
    repo = tmp_path / "greenfield2"
    shutil.copytree(demo_src, repo)

    def vacuous(wt: Path):
        (wt / "tests" / "acceptance").mkdir(parents=True, exist_ok=True)
        (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(
            "def test_ac1():\n    assert True\n")

    agent = MockAgent(actor_steps=[], test_author_steps=[vacuous, vacuous, vacuous])
    state = trigger.run(demo_src / "specs" / "daily-limit.md", repo,
                        agent=agent, caps=Caps(), gate_mode="synthesize",
                        runs_dir=tmp_path / "runs", worktree_root=tmp_path / ".wt")
    assert state["status"] == "escalated"
    assert state["result"]["outcome"].startswith("gate:")
    assert state["iterations"] == []                    # the loop never started


def test_cli_rejects_unknown_gate_mode():
    import pytest
    # argparse exits (code 2) on a value outside choices, before run() is reached
    with pytest.raises(SystemExit):
        trigger.main(["run", "--spec", "s", "--repo", "r", "--gate", "bogus"])
```

(`tests/test_trigger.py` already imports `shutil`, `Path`, `trigger`, `config`, `MockAgent`, `Caps` — extend imports only if missing.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_trigger.py -q`
Expected: FAIL — `TypeError: run() got an unexpected keyword argument 'gate_mode'`; the CLI test fails because `--gate` is an unknown argument (argparse exits 2 — which `pytest.raises(SystemExit)` treats as pass, so watch that this one may already pass; that is acceptable).

- [ ] **Step 3: Implement**

In `loopengine/trigger.py`:

Add the import:

```python
from . import gate as gate_synthesis
from .reporter import NullReporter
```

Change `run()`:

```python
def run(spec_path: Path, repo: Path, agent: Agent | None = None,
        caps: Caps | None = None, runs_dir: Path | None = None,
        worktree_root: Path | None = None, constitution_path: Path | None = None,
        reporter: Reporter | None = None, gate_mode: str = "provided") -> dict:
    spec_path, repo = Path(spec_path), Path(repo)
    agent = agent or ClaudeAgent()  # dev default; --agent overrides via main()
    caps = caps or Caps()
    reporter = reporter or NullReporter()
    runs_dir = Path(runs_dir) if runs_dir else RUNS_DIR
    worktree_root = Path(worktree_root) if worktree_root else (ROOT / ".worktrees")

    ensure_demo_repo(repo)  # idempotent; no-op for an already-git repo
    spec_text = spec_path.read_text(encoding="utf-8")
    constitution = _resolve_constitution(repo, constitution_path)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    branch = f"loop/{run_id}"
    memory = Memory.create(runs_dir, run_id, str(spec_path), str(repo), branch, caps)

    base = "main"
    if gate_mode == "synthesize":
        result = gate_synthesis.synthesize_gate(
            spec_text, repo, agent, memory, worktree_root, reporter)
        if not result["ok"]:
            reason = f"gate: {result['reason']}"
            reporter.finished("escalated", reason, None)
            memory.finish("escalated", reason, artifact=None)
            return memory.state
        base = result["ref"]

    return run_loop(spec_text, repo, agent, caps, memory, constitution,
                    worktree_root, reporter, base=base)
```

In `main()`, add the flag and pass it through:

```python
    runp.add_argument("--gate", choices=["provided", "synthesize"], default="provided",
                      help="'synthesize': an independent test-author agent writes the "
                           "acceptance gate from the spec before the loop (phase 0); "
                           "'provided' (default): the repo's committed tests are the gate")
```

```python
    state = run(Path(args.spec), Path(args.repo), agent=BACKENDS[args.agent](),
                caps=caps, constitution_path=constitution_path,
                reporter=_build_reporter(), gate_mode=args.gate)
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add loopengine/trigger.py tests/test_trigger.py
git commit -m "feat: --gate synthesize wires phase 0 into the run (fail closed, loop never starts)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: docs — runbook Scenario 4 + README

**Files:**
- Modify: `docs/DEMO-RUNBOOK.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: the working `--gate synthesize` flow from Task 10.
- Produces: presenter instructions for the self-authored-gate demo.

- [ ] **Step 1: Add Scenario 4 to the runbook**

In `docs/DEMO-RUNBOOK.md`: add a row to the scenario table at the top:

```markdown
| 4 | Self-authored gate (spec → tests → code) | `demo/greenfield-transfer` | loop writes its own gate, then converges | High (record it) |
```

Then append this section after Scenario 3:

```markdown
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
`git show gate/<run-id>:tests/acceptance/test_daily_limit.py` — the tests the
loop wrote and was graded against. Point out the actor could not edit them
(phase B), and the vacuity check proved they were red before implementation.

**If gate synthesis fails live:** that IS the safety story — the run escalates
and the loop never starts. Narrate it and rerun (or cut to the recording).
```

- [ ] **Step 2: Update the README**

In `README.md`, add a row to the demo-scenarios table:

```markdown
| Self-authored gate | `demo/greenfield-transfer` + `--gate synthesize` | test-author agent writes the gate from the spec, then the loop implements against it |
```

and extend the "New CLI flags" sentence to mention `--gate synthesize` (phase 0: gate synthesis; default `provided`).

- [ ] **Step 3: Run the full suite one last time**

Run: `.venv/bin/python -m pytest -q`
Expected: all green (~65 passed, 1 skipped).

- [ ] **Step 4: Commit**

```bash
git add docs/DEMO-RUNBOOK.md README.md
git commit -m "docs: runbook Scenario 4 — the loop authors its own acceptance gate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Deviations from the spec (intentional, minor)

- `test_author` argument order is `(spec, last_error, worktree)` to mirror `actor`, vs. the spec prose's `(spec, worktree, last_error)`. Signature consistency wins.
- The author-scope rule is stricter than the spec's "keep only tests/ writes": only **new files** under `tests/` are kept; modifications to *existing* tests are reverted too. Required by the compounding-suite decision — the gate author must not weaken prior features' gates.
- Reporter `gate()` takes `(status, detail)` and may be called several times per synthesis (per attempt + final), matching how `phase()` is used.
- The PR artifact keeps its current format (implementation-only diff); the gate's
  test-file list lives in `state["gate"]["tests"]` (memory) rather than being
  appended to the artifact. The spec's "artifact lists the gate's test files" is
  served by the auditable memory record; extending `write_pr_artifact` is a
  trivial follow-up if the human-review UX wants it inline.

## Post-plan verification (manual, not CI)

After all tasks: one live rehearsal per the runbook —
`.venv/bin/python -m loopengine run --spec demo/greenfield-transfer/specs/daily-limit.md --repo demo/greenfield-transfer --agent claude --gate synthesize` — and record it.
