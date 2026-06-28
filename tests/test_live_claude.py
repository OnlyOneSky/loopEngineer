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
