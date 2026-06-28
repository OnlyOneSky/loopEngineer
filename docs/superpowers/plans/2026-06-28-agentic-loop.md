# Spec-to-PR agentic loop — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable Python prototype that ingests a pre-approved `spec.md` and runs a bounded Codex Actor↔Critic loop against a real codebase, converging on a reviewed, constitution-compliant change (a local PR artifact) or escalating safely.

**Architecture:** One module per agentic-loop building block (`trigger`=Automations, `isolation`=Worktrees, `agents`=Sub-agents, `connectors`=Connectors, `memory`=Memory, plus `skills/`=Skills) glued by a thin `orchestrator.run_loop`. All model work goes through a small `Agent` seam with a real `CodexAgent` (`codex exec`) and a scriptable `MockAgent` so the loop is fully testable offline.

**Tech Stack:** Python 3.11+, stdlib only (subprocess, pathlib, json, dataclasses, argparse, uuid, datetime), `pytest` for both the prototype's tests and as the loop's real test gate. Codex CLI for production runs.

## Global Constraints

- Python 3.11+ (uses `X | None` and `tuple[...]` builtins generics).
- No third-party runtime dependencies — stdlib only. `pytest` is dev/test + the loop's gate.
- Three agent backends behind one `Agent` seam (identical contract): `MockAgent` (offline tests), `ClaudeAgent` (real runs on the dev machine via `claude -p`), `CodexAgent` (production work machine via `codex exec`). Selected by `--agent {mock,claude,codex}`, default `claude`.
- Production runtime is **Codex CLI only**. Actor = `codex exec --sandbox workspace-write`; critics = `codex exec --sandbox read-only`. Dev `ClaudeAgent`: actor = `claude -p --permission-mode acceptEdits --allowedTools "Read,Edit,Write"`; critic = `claude -p --allowedTools "Read" --output-format json` (parse `json.loads(stdout)["result"]`, then extract the JSON verdict).
- Safety caps are owned by our code, never the agent: `MAX_ITERATIONS = 6`, `MAX_WALL_SECONDS = 1200`.
- Protected paths (read-only to the actor, enforced after each turn): `("tests/", "constitution.md")`.
- Critic output is strict JSON: `{"verdict": "pass"|"fail", ...}` (QA uses `gaps`, Security uses `findings`).
- Iteration strategy: **full re-attempt with feedback** (favor correctness over token cost), per spec §11a.
- Tests live with the code they test under `tests/` mirroring `loopengine/`.
- Sentence-case commit messages, conventional-commit prefixes (`feat:`, `test:`, `chore:`, `docs:`).

---

### Task 1: Project scaffold + config

**Files:**
- Create: `.gitignore`
- Create: `loopengine/__init__.py`
- Create: `loopengine/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `config.MAX_ITERATIONS: int`, `config.MAX_WALL_SECONDS: int`, `config.PROTECTED: tuple[str, ...]`, `config.ROOT: Path`, `config.SKILLS_DIR: Path`, `config.PROMPTS_DIR: Path`, `config.RUNS_DIR: Path`, and `config.Caps` dataclass with fields `max_iterations: int`, `max_wall_seconds: int`.

- [ ] **Step 1: Initialise the git repo (project is not yet versioned)**

Run:
```bash
cd /Users/jeffchen/Projects/loopEngineer && git init -q && git add -A && git commit -q -m "chore: snapshot existing design docs" || true
```
Expected: a repo exists; existing `docs/` is committed.

- [ ] **Step 2: Write `.gitignore`**

Create `.gitignore`:
```gitignore
__pycache__/
*.pyc
.pytest_cache/
runs/
.worktrees/
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_config.py`:
```python
from loopengine import config


def test_caps_defaults_match_module_constants():
    caps = config.Caps()
    assert caps.max_iterations == config.MAX_ITERATIONS == 6
    assert caps.max_wall_seconds == config.MAX_WALL_SECONDS == 1200


def test_protected_paths():
    assert config.PROTECTED == ("tests/", "constitution.md")


def test_paths_anchor_to_project_root():
    assert config.SKILLS_DIR == config.ROOT / "skills"
    assert config.PROMPTS_DIR == config.SKILLS_DIR / "prompts"
    assert config.RUNS_DIR == config.ROOT / "runs"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'loopengine'`.

- [ ] **Step 5: Write `loopengine/__init__.py` (empty) and `loopengine/config.py`**

Create `loopengine/__init__.py` (empty file).

Create `loopengine/config.py`:
```python
"""Deterministic config + safety caps. The agent has no say over these."""
from dataclasses import dataclass
from pathlib import Path

MAX_ITERATIONS = 6
MAX_WALL_SECONDS = 1200
PROTECTED = ("tests/", "constitution.md")

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
PROMPTS_DIR = SKILLS_DIR / "prompts"
RUNS_DIR = ROOT / "runs"


@dataclass
class Caps:
    max_iterations: int = MAX_ITERATIONS
    max_wall_seconds: int = MAX_WALL_SECONDS
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add .gitignore loopengine/__init__.py loopengine/config.py tests/test_config.py
git commit -m "feat: project scaffold and safety config"
```

---

### Task 2: Memory — durable run state

**Files:**
- Create: `loopengine/memory.py`
- Test: `tests/test_memory.py`

**Interfaces:**
- Consumes: `config.Caps`.
- Produces: `Memory` dataclass with:
  - `Memory.create(runs_dir: Path, run_id: str, spec_path: str, repo: str, branch: str, caps: Caps) -> Memory`
  - `.add_iteration(n: int, elapsed_s: int) -> dict` (creates + returns the current iteration record)
  - `.update_iteration(**fields) -> None` (merges fields into the current iteration, then flushes)
  - `.finish(status: str, outcome: str, artifact: str | None = None) -> None`
  - `.state: dict`, `.path: Path`, `.run_dir: Path`
  - State persists to `<runs_dir>/<run_id>/state.json` on every mutation.

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory.py`:
```python
import json
from loopengine.config import Caps
from loopengine.memory import Memory


def test_create_writes_initial_state(tmp_path):
    m = Memory.create(tmp_path, "run-1", "spec.md", "repo", "loop/run-1", Caps())
    assert m.path == tmp_path / "run-1" / "state.json"
    on_disk = json.loads(m.path.read_text())
    assert on_disk["run_id"] == "run-1"
    assert on_disk["status"] == "running"
    assert on_disk["caps"] == {"max_iterations": 6, "max_wall_seconds": 1200}
    assert on_disk["iterations"] == []


def test_iteration_lifecycle_persists(tmp_path):
    m = Memory.create(tmp_path, "run-2", "spec.md", "repo", "loop/run-2", Caps())
    m.add_iteration(1, elapsed_s=0)
    m.update_iteration(tests={"passed": False, "summary": "boom"}, last_error="Tests failed: boom")
    on_disk = json.loads(m.path.read_text())
    assert on_disk["iterations"][0]["n"] == 1
    assert on_disk["iterations"][0]["tests"]["passed"] is False
    assert on_disk["iterations"][0]["last_error"] == "Tests failed: boom"


def test_finish_sets_result(tmp_path):
    m = Memory.create(tmp_path, "run-3", "spec.md", "repo", "loop/run-3", Caps())
    m.finish("converged", "all gates passed", artifact="runs/run-3/pr-artifact.md")
    on_disk = json.loads(m.path.read_text())
    assert on_disk["status"] == "converged"
    assert on_disk["result"] == {"outcome": "all gates passed", "artifact": "runs/run-3/pr-artifact.md"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_memory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'loopengine.memory'`.

- [ ] **Step 3: Write `loopengine/memory.py`**

```python
"""Memory — durable run state outside any single conversation.

The loop's spine: every iteration's verdicts and last_error are flushed to disk
so a run is auditable and resumable. The agent forgets; the file does not.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Caps


@dataclass
class Memory:
    path: Path
    run_dir: Path
    state: dict = field(default_factory=dict)

    @classmethod
    def create(cls, runs_dir: Path, run_id: str, spec_path: str,
               repo: str, branch: str, caps: Caps) -> "Memory":
        run_dir = Path(runs_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "run_id": run_id,
            "spec_path": spec_path,
            "repo": repo,
            "branch": branch,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "caps": {"max_iterations": caps.max_iterations,
                     "max_wall_seconds": caps.max_wall_seconds},
            "status": "running",
            "iterations": [],
            "result": None,
        }
        m = cls(path=run_dir / "state.json", run_dir=run_dir, state=state)
        m._flush()
        return m

    def add_iteration(self, n: int, elapsed_s: int) -> dict:
        record = {"n": n, "elapsed_s": elapsed_s, "enforce": None,
                  "tests": None, "qa": None, "security": None, "last_error": None}
        self.state["iterations"].append(record)
        self._flush()
        return record

    def update_iteration(self, **fields) -> None:
        self.state["iterations"][-1].update(fields)
        self._flush()

    def finish(self, status: str, outcome: str, artifact: str | None = None) -> None:
        self.state["status"] = status
        self.state["result"] = {"outcome": outcome, "artifact": artifact}
        self._flush()

    def _flush(self) -> None:
        self.path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_memory.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add loopengine/memory.py tests/test_memory.py
git commit -m "feat: durable run-state memory module"
```

---

### Task 3: Skills assets + loader

**Files:**
- Create: `skills/constitution.md`
- Create: `skills/AGENTS.md`
- Create: `skills/prompts/actor.txt`
- Create: `skills/prompts/qa_critic.txt`
- Create: `skills/prompts/security_critic.txt`
- Create: `loopengine/skills.py`
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: `config.SKILLS_DIR`, `config.PROMPTS_DIR`.
- Produces: `skills.constitution() -> str`, `skills.prompt(name: str) -> str` (loads `skills/prompts/<name>.txt`).

- [ ] **Step 1: Create the constitution** (copied verbatim from the SecondBrain reference, the version-controlled rule set the Security Critic checks)

Create `skills/constitution.md`:
```markdown
# Engineering Constitution

> Version-controlled rule set. Every change produced by the agent loop is checked
> against these clauses by the Security Critic before convergence.
> This file is READ-ONLY to the coding agent (the Actor).

## §1 — Money is never floating point
All monetary amounts MUST use a fixed-point decimal type (e.g. `Decimal`),
never `float` or `double`. This includes intermediate calculations.

## §2 — Validate all external input
Any value originating outside the service MUST be validated before use.

## §3 — Every money movement leaves an audit trail
Any operation that moves, holds, or limits funds MUST write an audit record
(who, what, amount, timestamp, outcome). A blocked operation MUST also be audited.

## §4 — No customer PII in logs
Account numbers, names, balances MUST NOT be written to application logs.

## §5 — Fail closed on limits and authorization
When a limit or authorization check cannot be completed, the operation MUST be denied.
```

- [ ] **Step 2: Create the actor/critic prompts** (adapted from the SecondBrain reference; `actor.txt` now targets on-disk edits, critics emit strict JSON)

Create `skills/prompts/actor.txt`:
```text
You are an implementation engineer on a banking codebase. Implement the feature so
ALL acceptance criteria in the specification pass. You may read the existing code.

HARD CONSTRAINTS — violating these is a critical failure:
- You MUST NOT modify, delete, weaken, or skip any test file (anything under tests/).
- You MUST NOT modify the constitution file.
- You MUST NOT change acceptance criteria to make them easier to pass.

If a previous attempt failed, the failure feedback is below. Fix the ROOT CAUSE;
do not patch around the symptom. Edit the files on disk directly.

SPECIFICATION:
{spec}

FAILURE FEEDBACK FROM PREVIOUS ATTEMPT (empty on first attempt):
{last_error}
```

Create `skills/prompts/qa_critic.txt`:
```text
You are a QA reviewer. Deterministic tests have ALREADY passed before you are called.
Your job is the judgment tests cannot make: whether the acceptance criteria are
genuinely and completely satisfied (boundary values, exact-equal, empty/zero/negative).

You may READ code and tests. You MUST NOT propose editing tests to pass.
Output ONLY valid JSON, no markdown fences:
{{"verdict": "pass" | "fail", "gaps": [{{"criterion": "AC-N", "issue": "..."}}]}}

SPECIFICATION:
{spec}

CODE DIFF UNDER REVIEW:
{diff}

TEST RESULTS (all passing):
{test_summary}
```

Create `skills/prompts/security_critic.txt`:
```text
You are a security and compliance auditor. Check the code change against EVERY
applicable clause of the engineering constitution, clause by clause. You have
READ-ONLY access. Be strict: if money touches a float anywhere, that is a §1
violation even if tests pass.

Output ONLY valid JSON, no markdown fences:
{{"verdict": "pass" | "fail",
  "findings": [{{"clause": "§N", "status": "compliant"|"violated"|"not_applicable",
                "evidence": "<file:line or short quote>"}}]}}

FULL CONSTITUTION:
{constitution}

CODE DIFF UNDER REVIEW:
{diff}
```

Create `skills/AGENTS.md`:
```markdown
# House rules for agents in this repo

- Never modify anything under `tests/` or `constitution.md`. These are the target,
  not something you may change.
- Implement against the specification you are given; make the existing tests pass.
- Prefer fixed-point `Decimal` for money. Validate external input. Fail closed.
- Output exactly the JSON contract you are asked for, with no markdown fences.
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_skills.py`:
```python
from loopengine import skills


def test_constitution_has_money_clause():
    text = skills.constitution()
    assert "§1" in text
    assert "Decimal" in text


def test_prompt_loads_actor_template_with_placeholders():
    text = skills.prompt("actor")
    assert "{spec}" in text
    assert "{last_error}" in text


def test_critic_prompts_request_json_verdict():
    assert '"verdict"' in skills.prompt("qa_critic")
    assert '"verdict"' in skills.prompt("security_critic")
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_skills.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'loopengine.skills'`.

- [ ] **Step 5: Write `loopengine/skills.py`**

```python
"""Skills — codified project knowledge, read-only to the actor."""
from .config import PROMPTS_DIR, SKILLS_DIR


def constitution() -> str:
    return (SKILLS_DIR / "constitution.md").read_text(encoding="utf-8")


def prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_skills.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add skills/ loopengine/skills.py tests/test_skills.py
git commit -m "feat: skills assets (constitution, prompts) and loader"
```

---

### Task 4: Connectors — pytest gate, git helpers, PR artifact

**Files:**
- Create: `loopengine/connectors.py`
- Test: `tests/test_connectors.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure subprocess/IO helpers).
- Produces:
  - `run_tests(repo: Path) -> dict` → `{"passed": bool, "summary": str}`
  - `git_changed_paths(repo: Path) -> list[str]` (working-tree changes, names only)
  - `git_revert_paths(repo: Path, paths: list[str]) -> None`
  - `git_diff(repo: Path, base: str = "main") -> str`
  - `git_commit_all(repo: Path, message: str) -> None`
  - `write_pr_artifact(run_dir: Path, summary: str, diff: str, qa: dict, security: dict) -> Path`

- [ ] **Step 1: Write the failing test** (uses a tiny real git repo fixture)

Create `tests/test_connectors.py`:
```python
import json
import subprocess
from pathlib import Path
from loopengine import connectors


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_x.py").write_text("def test_ok():\n    assert 1 == 1\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "init"], check=True)
    return repo


def test_run_tests_passes(tmp_path):
    repo = _init_repo(tmp_path)
    result = connectors.run_tests(repo)
    assert result["passed"] is True


def test_run_tests_fails_and_reports(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "tests" / "test_x.py").write_text("def test_bad():\n    assert 1 == 2\n")
    result = connectors.run_tests(repo)
    assert result["passed"] is False
    assert "assert" in result["summary"].lower()


def test_changed_paths_and_revert(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "tests" / "test_x.py").write_text("def test_tamper():\n    assert True\n")
    assert "tests/test_x.py" in connectors.git_changed_paths(repo)
    connectors.git_revert_paths(repo, ["tests/test_x.py"])
    assert connectors.git_changed_paths(repo) == []


def test_write_pr_artifact(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    path = connectors.write_pr_artifact(
        run_dir, "add limit", "diff text",
        {"verdict": "pass", "gaps": []}, {"verdict": "pass", "findings": []})
    assert path == run_dir / "pr-artifact.md"
    body = path.read_text()
    assert "add limit" in body and "diff text" in body and "verdict" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_connectors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'loopengine.connectors'`.

- [ ] **Step 3: Write `loopengine/connectors.py`**

```python
"""Connectors — the loop's wiring to real systems.

The safety-critical connectors (running tests, opening the PR artifact) are OURS
and are never exposed for the agent to call — the agent cannot certify itself.
"""
import json
import subprocess
from pathlib import Path


def run_tests(repo: Path) -> dict:
    """DETERMINISTIC GATE. We run the tests ourselves; the agent never self-certifies."""
    proc = subprocess.run(["python", "-m", "pytest", "-q"],
                          cwd=repo, capture_output=True, text=True)
    return {"passed": proc.returncode == 0, "summary": proc.stdout + proc.stderr}


def git_changed_paths(repo: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                         capture_output=True, text=True).stdout
    return [line[3:] for line in out.splitlines() if line.strip()]


def git_revert_paths(repo: Path, paths: list[str]) -> None:
    if not paths:
        return
    # Discard tracked changes; remove untracked additions to protected paths.
    subprocess.run(["git", "-C", str(repo), "checkout", "--", *paths],
                   capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo), "clean", "-fdq", "--", *paths],
                   capture_output=True, text=True)


def git_diff(repo: Path, base: str = "main") -> str:
    return subprocess.run(["git", "-C", str(repo), "diff", base, "--", "."],
                          capture_output=True, text=True).stdout


def git_commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=loop@local",
                    "-c", "user.name=loopengine", "commit", "-q", "-m", message],
                   check=True)


def write_pr_artifact(run_dir: Path, summary: str, diff: str,
                      qa: dict, security: dict) -> Path:
    path = Path(run_dir) / "pr-artifact.md"
    path.write_text(
        f"# Proposed change — awaiting human merge\n\n"
        f"## Summary\n{summary}\n\n"
        f"## QA report\n```json\n{json.dumps(qa, indent=2, ensure_ascii=False)}\n```\n\n"
        f"## Security report\n```json\n{json.dumps(security, indent=2, ensure_ascii=False)}\n```\n\n"
        f"## Diff\n```diff\n{diff}\n```\n",
        encoding="utf-8")
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_connectors.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add loopengine/connectors.py tests/test_connectors.py
git commit -m "feat: connectors (pytest gate, git helpers, PR artifact)"
```

---

### Task 5: Isolation — worktree + protected-path enforcement

**Files:**
- Create: `loopengine/isolation.py`
- Test: `tests/test_isolation.py`

**Interfaces:**
- Consumes: `connectors.git_changed_paths`, `connectors.git_revert_paths`, `config.PROTECTED`.
- Produces:
  - `create_worktree(repo: Path, branch: str, root: Path) -> Path` (new worktree dir off `main`)
  - `cleanup_worktree(repo: Path, worktree: Path) -> None`
  - `assert_no_protected_changes(worktree: Path, protected: tuple[str, ...]) -> tuple[bool, str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_isolation.py`:
```python
import subprocess
from pathlib import Path
from loopengine import isolation
from loopengine.config import PROTECTED


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_x.py").write_text("def test_ok():\n    assert True\n")
    (repo / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "init"], check=True)
    return repo


def test_worktree_is_isolated_checkout(tmp_path):
    repo = _init_repo(tmp_path)
    wt = isolation.create_worktree(repo, "loop/run-1", tmp_path / ".wt")
    assert (wt / "app.py").exists()
    assert wt != repo
    isolation.cleanup_worktree(repo, wt)
    assert not wt.exists()


def test_enforce_detects_and_reverts_test_tampering(tmp_path):
    repo = _init_repo(tmp_path)
    wt = isolation.create_worktree(repo, "loop/run-2", tmp_path / ".wt")
    (wt / "tests" / "test_x.py").write_text("def test_ok():\n    assert True  # weakened\n")
    (wt / "app.py").write_text("x = 2\n")  # legitimate change, must survive
    ok, reason = isolation.assert_no_protected_changes(wt, PROTECTED)
    assert ok is False
    assert "tests/test_x.py" in reason
    assert (wt / "tests" / "test_x.py").read_text() == "def test_ok():\n    assert True\n"
    assert (wt / "app.py").read_text() == "x = 2\n"


def test_enforce_allows_non_protected_changes(tmp_path):
    repo = _init_repo(tmp_path)
    wt = isolation.create_worktree(repo, "loop/run-3", tmp_path / ".wt")
    (wt / "app.py").write_text("x = 99\n")
    ok, reason = isolation.assert_no_protected_changes(wt, PROTECTED)
    assert ok is True and reason == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_isolation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'loopengine.isolation'`.

- [ ] **Step 3: Write `loopengine/isolation.py`**

```python
"""Worktrees — isolated checkouts + read-only-tests enforcement.

We cannot see inside a Codex turn, so we let the actor write, then verify on disk
with git and roll back any forbidden path. Detect-and-revert is the anti-tamper control.
"""
import subprocess
from pathlib import Path

from . import connectors


def create_worktree(repo: Path, branch: str, root: Path) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    worktree = root / branch.replace("/", "_")
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q",
                    "-b", branch, str(worktree), "main"], check=True)
    return worktree


def cleanup_worktree(repo: Path, worktree: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force",
                    str(worktree)], capture_output=True, text=True)


def assert_no_protected_changes(worktree: Path,
                                protected: tuple[str, ...]) -> tuple[bool, str]:
    changed = connectors.git_changed_paths(worktree)
    violations = [f for f in changed
                  if f.startswith(protected) or f in protected]
    if violations:
        connectors.git_revert_paths(worktree, violations)
        return False, f"Actor modified protected files: {violations}"
    return True, ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_isolation.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add loopengine/isolation.py tests/test_isolation.py
git commit -m "feat: worktree isolation and protected-path enforcement"
```

---

### Task 6: Agents — the seam (Mock + Claude + Codex backends)

**Files:**
- Create: `loopengine/agents.py`
- Test: `tests/test_agents.py`

**Interfaces:**
- Consumes: `skills.prompt`, `config.PROMPTS_DIR`.
- Produces:
  - `Agent` protocol: `actor(spec: str, last_error: str, worktree: Path) -> None`; `qa_critic(spec: str, diff: str, test_summary: str) -> dict`; `security_critic(constitution: str, diff: str) -> dict`.
  - `CodexAgent` (production, `codex exec`).
  - `ClaudeAgent(model: str = "claude-opus-4-8", max_turns: int = 40)` (dev machine, `claude -p`).
  - `MockAgent(actor_steps: list[callable], qa_fn=None, security_fn=None)` — `actor_steps[i]` is `callable(worktree: Path) -> None`; defaults make both critics return `pass`.
  - `_last_json_line(stdout: str) -> dict` (JSONL final-event parser, for Codex).
  - `_extract_json(text: str) -> dict` (tolerant parser for fenced/prose-wrapped JSON, for Claude).

- [ ] **Step 1: Write the failing test**

Create `tests/test_agents.py`:
```python
from pathlib import Path
from loopengine import agents


def test_last_json_line_picks_final_json():
    stdout = 'progress line\n{"verdict": "pass", "gaps": []}\ntrailing noise'
    assert agents._last_json_line(stdout) == {"verdict": "pass", "gaps": []}


def test_extract_json_handles_fenced_and_prose():
    fenced = '```json\n{"verdict": "fail", "findings": []}\n```'
    assert agents._extract_json(fenced) == {"verdict": "fail", "findings": []}
    prose = 'Here is my verdict: {"verdict": "pass", "findings": []} — done.'
    assert agents._extract_json(prose) == {"verdict": "pass", "findings": []}


def test_claude_agent_parses_critic_envelope(monkeypatch, tmp_path):
    import subprocess as sp

    class _Done:
        stdout = '{"type": "result", "result": "{\\"verdict\\": \\"pass\\", \\"gaps\\": []}"}'

    monkeypatch.setattr(sp, "run", lambda *a, **k: _Done())
    agent = agents.ClaudeAgent()
    assert agent.qa_critic("s", "d", "t") == {"verdict": "pass", "gaps": []}


def test_mock_actor_runs_scripted_step(tmp_path):
    calls = []
    agent = agents.MockAgent(actor_steps=[lambda wt: calls.append(wt)])
    agent.actor("spec", "", tmp_path)
    assert calls == [tmp_path]


def test_mock_critics_default_to_pass(tmp_path):
    agent = agents.MockAgent(actor_steps=[lambda wt: None])
    assert agent.qa_critic("s", "d", "t")["verdict"] == "pass"
    assert agent.security_critic("c", "d")["verdict"] == "pass"


def test_mock_security_fn_override():
    agent = agents.MockAgent(
        actor_steps=[lambda wt: None],
        security_fn=lambda con, diff: {"verdict": "fail",
                                       "findings": [{"clause": "§1", "status": "violated",
                                                     "evidence": "float"}]})
    assert agent.security_critic("c", "d")["verdict"] == "fail"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'loopengine.agents'`.

- [ ] **Step 3: Write `loopengine/agents.py`**

```python
"""Sub-agents — maker (actor) and checkers (critics).

The maker/checker split is enforced by the SANDBOX, not just the prompt: critics
run `codex exec --sandbox read-only` and physically cannot edit a file.
"""
import json
import subprocess
from pathlib import Path
from typing import Callable, Protocol

from . import skills


def _last_json_line(stdout: str) -> dict:
    """Codex emits JSONL events; the final parseable line is the agent message."""
    for line in reversed(stdout.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {}


def _extract_json(text: str) -> dict:
    """Tolerant: handles a bare object, a ```json fence, or JSON embedded in prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return {}
    return {}


class Agent(Protocol):
    def actor(self, spec: str, last_error: str, worktree: Path) -> None: ...
    def qa_critic(self, spec: str, diff: str, test_summary: str) -> dict: ...
    def security_critic(self, constitution: str, diff: str) -> dict: ...


class CodexAgent:
    """Production agent. All model work is `codex exec`, Codex-only."""

    def actor(self, spec: str, last_error: str, worktree: Path) -> None:
        prompt = skills.prompt("actor").format(spec=spec, last_error=last_error or "(first attempt)")
        subprocess.run(
            ["codex", "exec", "--sandbox", "workspace-write", "--json",
             "--skip-git-repo-check", prompt],
            cwd=worktree, capture_output=True, text=True, timeout=600)

    def qa_critic(self, spec: str, diff: str, test_summary: str) -> dict:
        prompt = skills.prompt("qa_critic").format(spec=spec, diff=diff, test_summary=test_summary)
        return self._read_only_json(prompt)

    def security_critic(self, constitution: str, diff: str) -> dict:
        prompt = skills.prompt("security_critic").format(constitution=constitution, diff=diff)
        return self._read_only_json(prompt)

    def _read_only_json(self, prompt: str) -> dict:
        proc = subprocess.run(
            ["codex", "exec", "--sandbox", "read-only", "--json",
             "--skip-git-repo-check", prompt],
            capture_output=True, text=True, timeout=600)
        verdict = _last_json_line(proc.stdout)
        return verdict or {"verdict": "fail", "findings": [{"evidence": "no parseable verdict"}]}


class ClaudeAgent:
    """Dev-machine agent. Real end-to-end runs via headless `claude -p`, so every
    loop step is verified with a real agent here before the Codex demo."""

    def __init__(self, model: str = "claude-opus-4-8", max_turns: int = 40):
        self.model = model
        self.max_turns = max_turns

    def actor(self, spec: str, last_error: str, worktree: Path) -> None:
        prompt = skills.prompt("actor").format(spec=spec, last_error=last_error or "(first attempt)")
        subprocess.run(
            ["claude", "-p", prompt,
             "--permission-mode", "acceptEdits",
             "--allowedTools", "Read,Edit,Write",
             "--max-turns", str(self.max_turns)],
            cwd=worktree, capture_output=True, text=True, timeout=900)

    def qa_critic(self, spec: str, diff: str, test_summary: str) -> dict:
        return self._critic(skills.prompt("qa_critic").format(
            spec=spec, diff=diff, test_summary=test_summary))

    def security_critic(self, constitution: str, diff: str) -> dict:
        return self._critic(skills.prompt("security_critic").format(
            constitution=constitution, diff=diff))

    def _critic(self, prompt: str) -> dict:
        proc = subprocess.run(
            ["claude", "-p", prompt,
             "--allowedTools", "Read",
             "--output-format", "json",
             "--model", self.model],
            capture_output=True, text=True, timeout=600)
        try:
            result_text = json.loads(proc.stdout)["result"]
        except (json.JSONDecodeError, KeyError):
            result_text = proc.stdout
        return _extract_json(result_text) or {
            "verdict": "fail", "findings": [{"evidence": "no parseable verdict"}]}


class MockAgent:
    """Scriptable double so the loop is testable offline without any live agent."""

    def __init__(self, actor_steps: list[Callable[[Path], None]],
                 qa_fn: Callable[[str, str, str], dict] | None = None,
                 security_fn: Callable[[str, str], dict] | None = None):
        self._steps = list(actor_steps)
        self._qa = qa_fn or (lambda spec, diff, ts: {"verdict": "pass", "gaps": []})
        self._sec = security_fn or (lambda con, diff: {"verdict": "pass", "findings": []})

    def actor(self, spec: str, last_error: str, worktree: Path) -> None:
        self._steps.pop(0)(worktree)

    def qa_critic(self, spec: str, diff: str, test_summary: str) -> dict:
        return self._qa(spec, diff, test_summary)

    def security_critic(self, constitution: str, diff: str) -> dict:
        return self._sec(constitution, diff)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_agents.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add loopengine/agents.py tests/test_agents.py
git commit -m "feat: agent seam with Mock, Claude, and Codex backends"
```

---

### Task 7: Demo target repo — transfer-limit bank app

**Files:**
- Create: `demo/bankapp/bankapp/__init__.py`
- Create: `demo/bankapp/bankapp/transfer.py`
- Create: `demo/bankapp/tests/test_transfer.py`
- Create: `demo/bankapp/specs/transfer-limit.md`
- Create: `loopengine/demo.py` (helper that initialises the demo repo as a git repo)
- Test: `tests/test_demo.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `demo.ensure_demo_repo(path: Path) -> Path` (idempotently `git init` + commit the demo if `.git` absent).
- The demo's `tests/test_transfer.py` is the protected acceptance suite; the starting `transfer.py` does NOT implement the limit (so tests fail until the actor implements it).

- [ ] **Step 1: Write the demo app skeleton** (limit not yet implemented)

Create `demo/bankapp/bankapp/__init__.py` (empty).

Create `demo/bankapp/bankapp/transfer.py`:
```python
"""Transfer module. The daily cumulative limit check is NOT yet implemented —
the agent loop must add it to satisfy tests/test_transfer.py."""


class LimitExceeded(Exception):
    pass


def transfer(amount, daily_total, tier_limit, audit_log):
    """Record and 'execute' a transfer. Currently performs no limit check."""
    audit_log.append(("transfer", amount))
    return "OK"
```

- [ ] **Step 2: Write the protected acceptance tests** (include the exact-equal boundary + Decimal expectation)

Create `demo/bankapp/tests/test_transfer.py`:
```python
from decimal import Decimal
import pytest
from bankapp.transfer import transfer, LimitExceeded


def test_under_limit_allowed():
    log = []
    assert transfer(Decimal("10"), Decimal("0"), Decimal("100"), log) == "OK"


def test_over_limit_blocked():
    log = []
    with pytest.raises(LimitExceeded):
        transfer(Decimal("60"), Decimal("50"), Decimal("100"), log)


def test_exact_equal_boundary_allowed():
    """daily_total + amount == tier_limit must be allowed (>= vs > bug catcher)."""
    log = []
    assert transfer(Decimal("50"), Decimal("50"), Decimal("100"), log) == "OK"


def test_blocked_transfer_is_audited():
    log = []
    with pytest.raises(LimitExceeded):
        transfer(Decimal("60"), Decimal("50"), Decimal("100"), log)
    assert any(entry[0] == "blocked" for entry in log)
```

- [ ] **Step 3: Write the input spec**

Create `demo/bankapp/specs/transfer-limit.md`:
```markdown
# Feature: daily cumulative transfer-limit validation

## Summary
Before a transfer, check whether the customer's cumulative daily transfer amount
plus this transfer exceeds their tier limit; if so, block it and audit the block.

## Acceptance criteria
- AC-1: when daily_total + amount <= tier_limit, the transfer is allowed.
- AC-2: when daily_total + amount > tier_limit, raise LimitExceeded.
- AC-3: the exact-equal case (daily_total + amount == tier_limit) is ALLOWED.
- AC-4: a blocked transfer MUST append a ("blocked", amount) audit entry. (§3)
- AC-5: all monetary arithmetic uses Decimal, never float. (§1)

## Applicable constitution clauses
§1 (money is Decimal), §3 (money movement is audited), §5 (fail closed).
```

- [ ] **Step 4: Write the failing test for the demo helper**

Create `tests/test_demo.py`:
```python
import subprocess
from pathlib import Path
from loopengine.demo import ensure_demo_repo


def test_ensure_demo_repo_is_idempotent(tmp_path):
    src = tmp_path / "bankapp"
    (src / "bankapp").mkdir(parents=True)
    (src / "bankapp" / "transfer.py").write_text("x = 1\n")
    (src / "tests").mkdir()
    (src / "tests" / "test_t.py").write_text("def test_ok():\n    assert True\n")

    repo = ensure_demo_repo(src)
    assert (repo / ".git").exists()
    head1 = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout
    ensure_demo_repo(src)  # second call must not re-init or error
    head2 = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout
    assert head1 == head2
```

- [ ] **Step 5: Run test to verify it fails**

Run: `python -m pytest tests/test_demo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'loopengine.demo'`.

- [ ] **Step 6: Write `loopengine/demo.py`**

```python
"""Helper to initialise the demo bank app as a git repo (worktrees need one)."""
import subprocess
from pathlib import Path


def ensure_demo_repo(path: Path) -> Path:
    path = Path(path)
    if (path / ".git").exists():
        return path
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.email=loop@local",
                    "-c", "user.name=loopengine", "commit", "-q", "-m",
                    "chore: demo bankapp baseline"], check=True)
    return path
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_demo.py -v`
Expected: PASS (1 test).

- [ ] **Step 8: Commit**

```bash
git add demo/ loopengine/demo.py tests/test_demo.py
git commit -m "feat: transfer-limit demo repo and init helper"
```

---

### Task 8: Orchestrator — run_loop glue + the full demo narrative

**Files:**
- Create: `loopengine/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `isolation`, `connectors`, `skills`, `memory.Memory`, `config`, `agents.Agent`.
- Produces:
  - `run_loop(spec_text: str, repo: Path, agent: Agent, caps: Caps, memory: Memory, constitution: str, worktree_root: Path) -> dict` → returns the final `memory.state`.
  - Stage order per iteration: actor → enforce → tests → qa → security; short-circuit on first failure; record everything to `memory`; converge (commit + artifact) or escalate on cap.

- [ ] **Step 1: Write the failing tests** (the 3-attempt narrative + the escalate-on-cap path, both with MockAgent against a real temp git repo)

Create `tests/test_orchestrator.py`:
```python
import subprocess
from pathlib import Path
from loopengine import orchestrator, connectors
from loopengine.agents import MockAgent
from loopengine.config import Caps, PROTECTED
from loopengine.memory import Memory


def _bank_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "bank"
    (repo / "bankapp").mkdir(parents=True)
    (repo / "bankapp" / "__init__.py").write_text("")
    (repo / "bankapp" / "transfer.py").write_text(
        "class LimitExceeded(Exception):\n    pass\n\n"
        "def transfer(amount, daily_total, tier_limit, audit_log):\n"
        "    audit_log.append(('transfer', amount))\n    return 'OK'\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_transfer.py").write_text(
        "from decimal import Decimal\nimport pytest\n"
        "from bankapp.transfer import transfer, LimitExceeded\n\n"
        "def test_under_limit_allowed():\n"
        "    assert transfer(Decimal('10'), Decimal('0'), Decimal('100'), []) == 'OK'\n\n"
        "def test_exact_equal_boundary_allowed():\n"
        "    assert transfer(Decimal('50'), Decimal('50'), Decimal('100'), []) == 'OK'\n\n"
        "def test_over_limit_blocked():\n"
        "    with pytest.raises(LimitExceeded):\n"
        "        transfer(Decimal('60'), Decimal('50'), Decimal('100'), [])\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "init"], check=True)
    return repo


# Actor step writers (simulate what Codex would edit on disk).
def _write_gt(wt: Path):  # uses '>' — fails the exact-equal boundary test
    (wt / "bankapp" / "transfer.py").write_text(
        "from decimal import Decimal\n"
        "class LimitExceeded(Exception):\n    pass\n\n"
        "def transfer(amount, daily_total, tier_limit, audit_log):\n"
        "    if daily_total + amount > tier_limit:\n"
        "        audit_log.append(('transfer', amount)); return 'OK'\n"
        "    audit_log.append(('blocked', amount)); raise LimitExceeded()\n")


def _write_float(wt: Path):  # passes tests but uses float -> §1 violation
    (wt / "bankapp" / "transfer.py").write_text(
        "class LimitExceeded(Exception):\n    pass\n\n"
        "def transfer(amount, daily_total, tier_limit, audit_log):\n"
        "    if float(daily_total) + float(amount) <= float(tier_limit):\n"
        "        audit_log.append(('transfer', amount)); return 'OK'\n"
        "    audit_log.append(('blocked', amount)); raise LimitExceeded()\n")


def _write_decimal(wt: Path):  # passes tests AND satisfies §1
    (wt / "bankapp" / "transfer.py").write_text(
        "from decimal import Decimal\n"
        "class LimitExceeded(Exception):\n    pass\n\n"
        "def transfer(amount, daily_total, tier_limit, audit_log):\n"
        "    if daily_total + amount <= tier_limit:\n"
        "        audit_log.append(('transfer', amount)); return 'OK'\n"
        "    audit_log.append(('blocked', amount)); raise LimitExceeded()\n")


def _security_fn(con, diff):
    return ({"verdict": "fail", "findings": [{"clause": "§1", "status": "violated",
                                              "evidence": "float()"}]}
            if "float(" in diff else {"verdict": "pass", "findings": []})


def test_three_attempt_narrative_converges(tmp_path):
    repo = _bank_repo(tmp_path)
    agent = MockAgent(actor_steps=[_write_gt, _write_float, _write_decimal],
                      security_fn=_security_fn)
    mem = Memory.create(tmp_path / "runs", "run-x", "spec.md", str(repo), "loop/run-x", Caps())
    state = orchestrator.run_loop("spec text", repo, agent, Caps(), mem,
                                  "constitution", tmp_path / ".wt")
    assert state["status"] == "converged"
    iters = state["iterations"]
    assert iters[0]["tests"]["passed"] is False          # attempt 1: boundary fail
    assert iters[1]["security"]["verdict"] == "fail"     # attempt 2: float §1
    assert iters[2]["security"]["verdict"] == "pass"     # attempt 3: decimal
    assert (Path(state["result"]["artifact"])).exists()


def test_escalates_on_iteration_cap(tmp_path):
    repo = _bank_repo(tmp_path)
    # Actor never fixes the boundary bug -> tests fail every attempt.
    agent = MockAgent(actor_steps=[_write_gt] * 3)
    caps = Caps(max_iterations=3)
    mem = Memory.create(tmp_path / "runs", "run-y", "spec.md", str(repo), "loop/run-y", caps)
    state = orchestrator.run_loop("spec text", repo, agent, caps, mem,
                                  "constitution", tmp_path / ".wt")
    assert state["status"] == "escalated"
    assert len(state["iterations"]) == 3
    assert "Tests failed" in state["iterations"][-1]["last_error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'loopengine.orchestrator'`.

- [ ] **Step 3: Write `loopengine/orchestrator.py`**

```python
"""The loop. The agent writes; OUR code verifies, gates, caps, and escalates.

Read run_loop top to bottom — every stage is triggered by the previous step's
code calling it. No magic agent-to-agent handoff.
"""
import time
from pathlib import Path

from . import isolation, connectors
from .agents import Agent
from .config import Caps, PROTECTED
from .memory import Memory


def run_loop(spec_text: str, repo: Path, agent: Agent, caps: Caps,
             memory: Memory, constitution: str, worktree_root: Path) -> dict:
    branch = memory.state["branch"]
    worktree = isolation.create_worktree(repo, branch, worktree_root)
    start = time.time()
    last_error = ""
    try:
        for attempt in range(1, caps.max_iterations + 1):
            elapsed = int(time.time() - start)
            memory.add_iteration(attempt, elapsed)
            if elapsed > caps.max_wall_seconds:
                memory.finish("escalated", "time cap", artifact=None)
                return memory.state

            # A. Actor (maker) — edits files on disk in the isolated worktree.
            agent.actor(spec_text, last_error, worktree)

            # B. Enforce read-only-tests rule AFTER the turn.
            ok, why = isolation.assert_no_protected_changes(worktree, PROTECTED)
            memory.update_iteration(enforce={"ok": ok, "reason": why})
            if not ok:
                last_error = why
                continue

            # C. Deterministic test gate — we run the tests ourselves.
            tests = connectors.run_tests(worktree)
            memory.update_iteration(tests={"passed": tests["passed"],
                                           "summary": tests["summary"][-2000:]})
            if not tests["passed"]:
                last_error = f"Tests failed:\n{tests['summary']}"
                continue

            diff = connectors.git_diff(worktree, "main")

            # D. QA critic (checker) — only meaningful after tests pass.
            qa = agent.qa_critic(spec_text, diff, tests["summary"])
            memory.update_iteration(qa=qa)
            if qa.get("verdict") != "pass":
                last_error = f"QA gaps:\n{qa.get('gaps')}"
                continue

            # E. Security critic (checker) — read-only vs the constitution.
            security = agent.security_critic(constitution, diff)
            memory.update_iteration(security=security)
            if security.get("verdict") != "pass":
                last_error = f"Constitution violations:\n{security.get('findings')}"
                continue

            # All gates passed -> commit + write the PR artifact for human merge.
            connectors.git_commit_all(worktree, f"agent: implement spec ({memory.state['run_id']})")
            artifact = connectors.write_pr_artifact(
                memory.run_dir, spec_text.splitlines()[0] if spec_text else "change",
                connectors.git_diff(worktree, "main"), qa, security)
            memory.finish("converged", "all gates passed", artifact=str(artifact))
            return memory.state

        memory.finish("escalated", f"iteration cap; last_error={last_error}", artifact=None)
        return memory.state
    finally:
        isolation.cleanup_worktree(repo, worktree)
```

> Note: `git_diff` against `main` is read before the commit (uncommitted changes vs `main`) and again after the commit for the artifact — both return the full feature diff, so the artifact is complete.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: PASS (2 tests) — the narrative converges; the cap path escalates.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add loopengine/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator run_loop with bounded actor-critic gating"
```

---

### Task 9: Trigger (CLI) + README

**Files:**
- Create: `loopengine/trigger.py`
- Create: `loopengine/__main__.py`
- Create: `README.md`
- Test: `tests/test_trigger.py`

**Interfaces:**
- Consumes: `demo.ensure_demo_repo`, `skills.constitution`, `memory.Memory`, `orchestrator.run_loop`, `agents.CodexAgent`, `config`.
- Produces:
  - `run(spec_path: Path, repo: Path, agent=None, caps=None, runs_dir=None, worktree_root=None) -> dict` → final state. `agent` defaults to `CodexAgent()`.
  - `main(argv: list[str] | None = None) -> int` (argparse CLI: `--spec`, `--repo`).

- [ ] **Step 1: Write the failing test** (drives the whole loop through the public entrypoint with a MockAgent; reuses the demo repo helpers)

Create `tests/test_trigger.py`:
```python
import shutil
from pathlib import Path
from loopengine import trigger, config
from loopengine.agents import MockAgent
from loopengine.config import Caps


def _decimal_actor(wt: Path):
    (wt / "bankapp" / "transfer.py").write_text(
        "from decimal import Decimal\n"
        "class LimitExceeded(Exception):\n    pass\n\n"
        "def transfer(amount, daily_total, tier_limit, audit_log):\n"
        "    if daily_total + amount <= tier_limit:\n"
        "        audit_log.append(('transfer', amount)); return 'OK'\n"
        "    audit_log.append(('blocked', amount)); raise LimitExceeded()\n")


def test_run_against_demo_repo_converges(tmp_path):
    # Copy the committed demo repo into a temp dir so the test doesn't dirty it.
    demo_src = config.ROOT / "demo" / "bankapp"
    repo = tmp_path / "bankapp"
    shutil.copytree(demo_src, repo)
    agent = MockAgent(actor_steps=[_decimal_actor])
    state = trigger.run(demo_src / "specs" / "transfer-limit.md", repo,
                        agent=agent, caps=Caps(),
                        runs_dir=tmp_path / "runs", worktree_root=tmp_path / ".wt")
    assert state["status"] == "converged"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trigger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'loopengine.trigger'`.

- [ ] **Step 3: Write `loopengine/trigger.py`**

```python
"""Automations — the manual entrypoint that ingests spec.md and kicks the loop.

In production the Kanban card-move fires this via a connector; here it is a CLI call.
This module also owns the safety caps; the agent has no say over them.
"""
import argparse
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import skills
from .agents import Agent, ClaudeAgent, CodexAgent, MockAgent
from .config import Caps, RUNS_DIR, ROOT
from .demo import ensure_demo_repo
from .memory import Memory
from .orchestrator import run_loop

BACKENDS = {"claude": ClaudeAgent, "codex": CodexAgent}


def run(spec_path: Path, repo: Path, agent: Agent | None = None,
        caps: Caps | None = None, runs_dir: Path | None = None,
        worktree_root: Path | None = None) -> dict:
    spec_path, repo = Path(spec_path), Path(repo)
    agent = agent or ClaudeAgent()  # dev default; --agent overrides via main()
    caps = caps or Caps()
    runs_dir = Path(runs_dir) if runs_dir else RUNS_DIR
    worktree_root = Path(worktree_root) if worktree_root else (ROOT / ".worktrees")

    ensure_demo_repo(repo)  # idempotent; no-op for an already-git repo
    spec_text = spec_path.read_text(encoding="utf-8")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    branch = f"loop/{run_id}"
    memory = Memory.create(runs_dir, run_id, str(spec_path), str(repo), branch, caps)
    return run_loop(spec_text, repo, agent, caps, memory, skills.constitution(), worktree_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loopengine")
    sub = parser.add_subparsers(dest="cmd", required=True)
    runp = sub.add_parser("run", help="run the loop against a spec")
    runp.add_argument("--spec", required=True)
    runp.add_argument("--repo", required=True)
    runp.add_argument("--agent", choices=list(BACKENDS), default="claude",
                      help="agent backend (default: claude; use codex on the work machine)")
    args = parser.parse_args(argv)

    state = run(Path(args.spec), Path(args.repo), agent=BACKENDS[args.agent]())
    print(f"\nstatus: {state['status']}")
    if state.get("result"):
        print(f"outcome: {state['result']['outcome']}")
        if state["result"].get("artifact"):
            print(f"artifact: {state['result']['artifact']}")
    return 0 if state["status"] == "converged" else 1
```

- [ ] **Step 4: Write `loopengine/__main__.py`**

```python
import sys
from .trigger import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_trigger.py -v`
Expected: PASS (1 test).

- [ ] **Step 6: Write `README.md`**

```markdown
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

## Run the offline test suite (mock agent, no keys)

```bash
python -m pytest -q                      # the prototype's own tests, incl. the 3-attempt demo
```

## Run for real on THIS dev machine (Claude Code)

```bash
python -m loopengine run \
  --spec demo/bankapp/specs/transfer-limit.md \
  --repo demo/bankapp \
  --agent claude        # default; verifies every loop step with a real agent
```

Optional live end-to-end test: `LOOP_LIVE=claude python -m pytest tests/test_live_claude.py -v`.

## Run for the demo on the work machine (Codex CLI)

```bash
python -m loopengine run \
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
```

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add loopengine/trigger.py loopengine/__main__.py README.md tests/test_trigger.py
git commit -m "feat: CLI trigger entrypoint and README"
```

---

### Task 10: Codex de-risking — smoke script, real-output fixture, opt-in live Claude test

**Files:**
- Create: `scripts/codex_smoke.py`
- Create: `tests/fixtures/codex_events.jsonl` (placeholder sample, replaced on the work machine)
- Create: `tests/test_codex_parse.py`
- Create: `tests/test_live_claude.py`

**Interfaces:**
- Consumes: `agents._last_json_line`, `agents.CodexAgent`, `trigger.run`, `agents.ClaudeAgent`.
- Produces: a runnable smoke script + a parse test pinned to a real Codex sample + an opt-in live test. No new production module.

**Context:** `CodexAgent` cannot run on the dev machine. This task makes its one
risk (parsing real `codex exec --json` output) testable against a captured sample,
and makes the live `ClaudeAgent` path demonstrable here.

- [ ] **Step 1: Write the smoke script** (run once on the work machine)

Create `scripts/codex_smoke.py`:
```python
"""Run ONCE on the work machine to (a) confirm `codex exec` flags work and
(b) capture a real --json event stream as a test fixture.

Usage:
    python scripts/codex_smoke.py > tests/fixtures/codex_events.jsonl
Then sanity-check the last line is the final agent message, and commit the fixture.
"""
import subprocess
import sys

PROMPT = "Reply with the single word OK. Do not edit any files."

proc = subprocess.run(
    ["codex", "exec", "--sandbox", "read-only", "--json",
     "--skip-git-repo-check", PROMPT],
    capture_output=True, text=True, timeout=300)
sys.stderr.write(f"[codex_smoke] returncode={proc.returncode}\n")
sys.stderr.write(f"[codex_smoke] stderr tail:\n{proc.stderr[-500:]}\n")
sys.stdout.write(proc.stdout)
```

- [ ] **Step 2: Create a placeholder fixture** (a realistic synthetic line; replace with real output on the work machine)

Create `tests/fixtures/codex_events.jsonl`:
```jsonl
{"type":"item.started","item":{"type":"agent_message"}}
{"type":"item.completed","item":{"type":"agent_message","text":"placeholder"}}
{"verdict":"pass","findings":[{"clause":"§1","status":"compliant","evidence":"uses Decimal"}]}
```

- [ ] **Step 3: Write the failing parse test**

Create `tests/test_codex_parse.py`:
```python
from pathlib import Path
from loopengine import agents


def test_last_json_line_parses_real_codex_sample():
    sample = (Path(__file__).parent / "fixtures" / "codex_events.jsonl").read_text()
    verdict = agents._last_json_line(sample)
    # The fixture's final JSON line is the verdict object the orchestrator consumes.
    assert verdict.get("verdict") == "pass"
    assert verdict["findings"][0]["clause"] == "§1"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_codex_parse.py -v`
Expected: PASS (1 test). (After capturing real output on the work machine, re-run to
confirm the real event schema still ends in a parseable verdict line; if Codex wraps
the verdict differently, adjust `CodexAgent._read_only_json` then — that is the one
place the real schema matters.)

- [ ] **Step 5: Write the opt-in live Claude test**

Create `tests/test_live_claude.py`:
```python
import os
import shutil
import pytest
from loopengine import trigger, config
from loopengine.agents import ClaudeAgent
from loopengine.config import Caps


@pytest.mark.skipif(os.environ.get("LOOP_LIVE") != "claude",
                    reason="set LOOP_LIVE=claude to run a real ClaudeAgent loop")
def test_live_claude_converges_on_demo(tmp_path):
    demo_src = config.ROOT / "demo" / "bankapp"
    repo = tmp_path / "bankapp"
    shutil.copytree(demo_src, repo)
    state = trigger.run(demo_src / "specs" / "transfer-limit.md", repo,
                        agent=ClaudeAgent(), caps=Caps(),
                        runs_dir=tmp_path / "runs", worktree_root=tmp_path / ".wt")
    assert state["status"] == "converged"
```

- [ ] **Step 6: Verify the opt-in test is skipped by default, then run it live once**

Run (default, skipped): `python -m pytest tests/test_live_claude.py -v`
Expected: SKIPPED (1 skipped).

Run (live, real Claude — costs tokens, needs auth):
`LOOP_LIVE=claude python -m pytest tests/test_live_claude.py -v -s`
Expected: PASS — the real `ClaudeAgent` implements the transfer limit, tests pass,
critics pass, the loop converges and writes a PR artifact. This is the "every step
works with a real agent" proof on the dev machine.

- [ ] **Step 7: Run the full offline suite**

Run: `python -m pytest -q -k "not live"`
Expected: all tests PASS (live test skipped).

- [ ] **Step 8: Commit**

```bash
git add scripts/codex_smoke.py tests/fixtures/codex_events.jsonl tests/test_codex_parse.py tests/test_live_claude.py
git commit -m "feat: codex smoke script, real-output fixture, opt-in live claude test"
```

---

## Self-review (completed)

**Spec coverage:** §4 layout → Tasks 1–9 create every named module. §5 loop flow → Task 8 `run_loop` implements all stages in order. §6 building blocks → one task each (trigger T9, isolation T5, skills T3, connectors T4, agents T6, memory T2). §7 data contracts → memory shape (T2), critic JSON (T6), spec.md ingest (T9). §8 safety table → caps (T1/T8), enforce+revert (T5), read-only critics (T6), pytest-first ordering (T8), no auto-merge / PR artifact (T4/T8). §9 demo → T7 + the narrative test in T8. §11 testing seam → MockAgent (T6) used throughout. §11a iteration strategy → full re-attempt with `last_error` fed to actor (T8). §12 Codex `--json` parsing → `_last_json_line` (T6).

**Placeholder scan:** no TBD/TODO; every code step shows complete code; every test step shows real assertions.

**Type consistency:** `Memory.create/add_iteration/update_iteration/finish` consistent T2↔T8↔T9. `Agent` methods (`actor/qa_critic/security_critic`) consistent T6↔T8. `connectors.git_changed_paths/git_revert_paths/git_diff/git_commit_all/run_tests/write_pr_artifact` consistent T4↔T5↔T8. `run_loop` signature consistent T8↔T9. `Caps(max_iterations,max_wall_seconds)` consistent T1↔T8↔T9.

**Portability coverage (spec §3a):** three backends behind one `Agent` seam —
`MockAgent` (all offline tests), `ClaudeAgent` (T6 unit test for envelope parsing +
T10 opt-in live loop on the dev machine), `CodexAgent` (T6 construction + T10 parse
test against a real captured `tests/fixtures/codex_events.jsonl`). Selection via
`--agent {claude,codex}` (T9).

**Known integration caveat (carry into execution):** the real `CodexAgent` cannot run
on the dev machine. T10 covers its parse layer against a *placeholder* fixture; on the
work machine, run `scripts/codex_smoke.py` first to replace the fixture with real
output and confirm `--sandbox read-only` ends in a parseable verdict line and
`--sandbox workspace-write` edits the worktree (spec §12). If the real Codex schema
differs, the only change needed is `CodexAgent._read_only_json` parsing. Also verify
the `claude` CLI flags in T6 against `claude --help` before the first live run
(`--permission-mode acceptEdits`, `--allowedTools`, `--output-format json`).
```
