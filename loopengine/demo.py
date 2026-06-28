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
