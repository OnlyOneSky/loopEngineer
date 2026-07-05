"""Worktrees — isolated checkouts + read-only-tests enforcement.

We cannot see inside a Codex turn, so we let the actor write, then verify on disk
with git and roll back any forbidden path. Detect-and-revert is the anti-tamper control.
"""
import subprocess
from pathlib import Path

from . import connectors


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
