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
