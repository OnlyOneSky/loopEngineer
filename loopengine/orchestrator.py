"""The loop. The agent writes; OUR code verifies, gates, caps, and escalates.

Read run_loop top to bottom — every stage is triggered by the previous step's
code calling it. No magic agent-to-agent handoff. Each stage also narrates
itself through `reporter` (the live view) while `memory` records the durable
audit trail — two independent sinks, neither required for the loop to run.
"""
import time
from pathlib import Path

from . import isolation, connectors
from .agents import Agent
from .config import Caps, PROTECTED
from .memory import Memory
from .reporter import NullReporter, Reporter


def run_loop(spec_text: str, repo: Path, agent: Agent, caps: Caps,
             memory: Memory, constitution: str, worktree_root: Path,
             reporter: Reporter | None = None, base: str = "main") -> dict:
    reporter = reporter or NullReporter()
    branch = memory.state["branch"]
    worktree = isolation.create_worktree(repo, branch, worktree_root, base)
    start = time.time()
    last_error = ""
    spec_summary = _spec_summary(spec_text)
    reporter.run_start(memory.state["run_id"], spec_summary,
                       type(agent).__name__, caps.max_iterations)
    try:
        for attempt in range(1, caps.max_iterations + 1):
            elapsed = int(time.time() - start)
            memory.add_iteration(attempt, elapsed)
            reporter.iteration_start(attempt, caps.max_iterations, elapsed)
            if elapsed > caps.max_wall_seconds:
                reporter.finished("escalated", "time cap", None)
                memory.finish("escalated", "time cap", artifact=None)
                return memory.state

            # A. Actor (maker) — edits files on disk in the isolated worktree.
            agent.actor(spec_text, last_error, worktree)
            changed = connectors.git_changed_paths(worktree)
            reporter.phase("A", "Actor", "info", f"{len(changed)} path(s) changed")

            # B. Enforce read-only-tests rule AFTER the turn.
            ok, why = isolation.assert_no_protected_changes(worktree, PROTECTED)
            memory.update_iteration(enforce={"ok": ok, "reason": why})
            reporter.phase("B", "Enforce", "ok" if ok else "fail",
                           "protected paths clean" if ok else why)
            if not ok:
                last_error = why
                memory.update_iteration(last_error=last_error)
                reporter.retry(last_error)
                continue

            # C. Deterministic test gate — we run the tests ourselves.
            tests = connectors.run_tests(worktree)
            memory.update_iteration(tests={"passed": tests["passed"],
                                           "summary": tests["summary"][-2000:]})
            reporter.phase("C", "Tests", "ok" if tests["passed"] else "fail",
                           _test_headline(tests["summary"]))
            if not tests["passed"]:
                last_error = f"Tests failed:\n{tests['summary']}"
                memory.update_iteration(last_error=last_error)
                reporter.retry(f"tests failed: {_test_headline(tests['summary'])}")
                continue

            diff = connectors.git_diff(worktree, base)

            # D. QA critic (checker) — only meaningful after tests pass.
            qa = agent.qa_critic(spec_text, diff, tests["summary"])
            memory.update_iteration(qa=qa)
            qa_pass = qa.get("verdict") == "pass"
            reporter.phase("D", "QA", "ok" if qa_pass else "fail",
                           "acceptance criteria met" if qa_pass else _short(qa.get("gaps")))
            if not qa_pass:
                last_error = f"QA gaps:\n{qa.get('gaps')}"
                memory.update_iteration(last_error=last_error)
                reporter.retry(f"QA gaps: {_short(qa.get('gaps'))}")
                continue

            # E. Security critic (checker) — read-only vs the constitution.
            security = agent.security_critic(constitution, diff)
            memory.update_iteration(security=security)
            sec_pass = security.get("verdict") == "pass"
            reporter.phase("E", "Security", "ok" if sec_pass else "fail",
                           "constitution satisfied" if sec_pass else _short(security.get("findings")))
            if not sec_pass:
                last_error = f"Constitution violations:\n{security.get('findings')}"
                memory.update_iteration(last_error=last_error)
                reporter.retry(f"constitution violations: {_short(security.get('findings'))}")
                continue

            # All gates passed -> commit + write the PR artifact for human merge.
            connectors.git_commit_all(worktree, f"agent: implement spec ({memory.state['run_id']})")
            artifact = connectors.write_pr_artifact(
                memory.run_dir, spec_summary,
                connectors.git_diff(worktree, base), qa, security)
            reporter.finished("converged", "all gates passed", str(artifact))
            memory.finish("converged", "all gates passed", artifact=str(artifact))
            return memory.state

        reporter.finished("escalated", f"iteration cap; last_error={last_error}", None)
        memory.finish("escalated", f"iteration cap; last_error={last_error}", artifact=None)
        return memory.state
    finally:
        isolation.cleanup_worktree(repo, worktree)


def _spec_summary(spec_text: str) -> str:
    if not spec_text.strip():
        return "change"
    return spec_text.splitlines()[0].lstrip("# ").strip() or "change"


def _test_headline(summary: str) -> str:
    """The one line a human reads from pytest output (e.g. '4 passed', '1 failed')."""
    for line in reversed((summary or "").strip().splitlines()):
        line = line.strip().strip("=").strip()
        if "passed" in line or "failed" in line or "error" in line:
            return line
    return ""


def _short(obj, limit: int = 120) -> str:
    text = str(obj) if obj is not None else ""
    return text if len(text) <= limit else text[: limit - 1] + "…"
