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
