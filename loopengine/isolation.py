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
