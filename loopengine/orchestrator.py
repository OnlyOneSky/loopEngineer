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
                memory.update_iteration(last_error=last_error)
                continue

            # C. Deterministic test gate — we run the tests ourselves.
            tests = connectors.run_tests(worktree)
            memory.update_iteration(tests={"passed": tests["passed"],
                                           "summary": tests["summary"][-2000:]})
            if not tests["passed"]:
                last_error = f"Tests failed:\n{tests['summary']}"
                memory.update_iteration(last_error=last_error)
                continue

            diff = connectors.git_diff(worktree, "main")

            # D. QA critic (checker) — only meaningful after tests pass.
            qa = agent.qa_critic(spec_text, diff, tests["summary"])
            memory.update_iteration(qa=qa)
            if qa.get("verdict") != "pass":
                last_error = f"QA gaps:\n{qa.get('gaps')}"
                memory.update_iteration(last_error=last_error)
                continue

            # E. Security critic (checker) — read-only vs the constitution.
            security = agent.security_critic(constitution, diff)
            memory.update_iteration(security=security)
            if security.get("verdict") != "pass":
                last_error = f"Constitution violations:\n{security.get('findings')}"
                memory.update_iteration(last_error=last_error)
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
