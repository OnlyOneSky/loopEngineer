"""Automations — the manual entrypoint that ingests spec.md and kicks the loop.

In production the Kanban card-move fires this via a connector; here it is a CLI call.
This module also owns the safety caps; the agent has no say over them.
"""
import argparse
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import skills
from .agents import Agent, ClaudeAgent, CodexAgent
from .config import Caps, MAX_ITERATIONS, RUNS_DIR, ROOT
from .demo import ensure_demo_repo
from .memory import Memory
from .orchestrator import run_loop
from .reporter import ConsoleReporter, MultiReporter, Reporter, SlackReporter
from .slack import SlackPoster

BACKENDS = {"claude": ClaudeAgent, "codex": CodexAgent}


def run(spec_path: Path, repo: Path, agent: Agent | None = None,
        caps: Caps | None = None, runs_dir: Path | None = None,
        worktree_root: Path | None = None, constitution_path: Path | None = None,
        reporter: Reporter | None = None) -> dict:
    spec_path, repo = Path(spec_path), Path(repo)
    agent = agent or ClaudeAgent()  # dev default; --agent overrides via main()
    caps = caps or Caps()
    runs_dir = Path(runs_dir) if runs_dir else RUNS_DIR
    worktree_root = Path(worktree_root) if worktree_root else (ROOT / ".worktrees")

    ensure_demo_repo(repo)  # idempotent; no-op for an already-git repo
    spec_text = spec_path.read_text(encoding="utf-8")
    constitution = _resolve_constitution(repo, constitution_path)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    branch = f"loop/{run_id}"
    memory = Memory.create(runs_dir, run_id, str(spec_path), str(repo), branch, caps)
    return run_loop(spec_text, repo, agent, caps, memory, constitution,
                    worktree_root, reporter)


def _resolve_constitution(repo: Path, explicit: Path | None) -> str:
    """--constitution wins; else a constitution.md carried by the repo; else the
    default skills constitution. Lets each demo domain bring its own rule set."""
    if explicit:
        return Path(explicit).read_text(encoding="utf-8")
    local = repo / "constitution.md"
    if local.exists():
        return local.read_text(encoding="utf-8")
    return skills.constitution()


def _caps_from_args(max_iterations: int | None) -> Caps:
    """A per-run --max-iterations, clamped to [1, MAX_ITERATIONS]. The human sets
    the demo cap; the hard ceiling is still owned by our code, not the agent."""
    if max_iterations is None:
        return Caps()
    return Caps(max_iterations=max(1, min(max_iterations, MAX_ITERATIONS)))


def _build_reporter() -> Reporter:
    """Console always; add Slack when SLACK_BOT_TOKEN + SLACK_CHANNEL are set."""
    reporters: list[Reporter] = [ConsoleReporter()]
    token, channel = os.environ.get("SLACK_BOT_TOKEN"), os.environ.get("SLACK_CHANNEL")
    if token and channel:
        reporters.append(SlackReporter(SlackPoster(token, channel)))
    return MultiReporter(reporters)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loopengine")
    sub = parser.add_subparsers(dest="cmd", required=True)
    runp = sub.add_parser("run", help="run the loop against a spec")
    runp.add_argument("--spec", required=True)
    runp.add_argument("--repo", required=True)
    runp.add_argument("--agent", choices=list(BACKENDS), default="claude",
                      help="agent backend (default: claude; use codex on the work machine)")
    runp.add_argument("--max-iterations", type=int, default=None,
                      help=f"iteration cap for THIS run, 1..{MAX_ITERATIONS} "
                           f"(default {MAX_ITERATIONS}); clamped to the hard ceiling")
    runp.add_argument("--constitution", default=None,
                      help="path to the constitution the security critic enforces "
                           "(default: the repo's own, else skills/constitution.md)")
    args = parser.parse_args(argv)

    caps = _caps_from_args(args.max_iterations)
    constitution_path = Path(args.constitution) if args.constitution else None

    state = run(Path(args.spec), Path(args.repo), agent=BACKENDS[args.agent](),
                caps=caps, constitution_path=constitution_path,
                reporter=_build_reporter())
    print(f"\nstatus: {state['status']}")
    if state.get("result"):
        print(f"outcome: {state['result']['outcome']}")
        if state["result"].get("artifact"):
            print(f"artifact: {state['result']['artifact']}")
    return 0 if state["status"] == "converged" else 1
