"""Connectors — the loop's wiring to real systems.

The safety-critical connectors (running tests, opening the PR artifact) are OURS
and are never exposed for the agent to call — the agent cannot certify itself.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def run_tests(repo: Path) -> dict:
    """DETERMINISTIC GATE. We run the tests ourselves; the agent never self-certifies.

    Uses sys.executable (the interpreter running the loop) so tests run under the
    same venv; the `-m pytest` form prepends cwd to sys.path so the target package
    in the worktree imports cleanly.
    Suppresses bytecode + pytest cache so the worktree stays clean for the
    post-run protected-path check."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                          cwd=repo, capture_output=True, text=True, env=env)
    return {"passed": proc.returncode == 0, "summary": proc.stdout + proc.stderr}


def git_changed_paths(repo: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                         capture_output=True, text=True).stdout
    paths = []
    for line in out.splitlines():
        if not line.strip():
            continue
        entry = line[3:]
        if " -> " in entry:                 # rename/copy: "old -> new"
            old, new = entry.split(" -> ", 1)
            paths.extend([old, new])
        else:
            paths.append(entry)
    return paths


def git_revert_paths(repo: Path, paths: list[str]) -> None:
    if not paths:
        return
    # Make index AND working tree match HEAD for these paths, defeating even a
    # STAGED tamper (git add): reset unstages, checkout restores tracked content
    # from the now-clean index, clean removes any untracked/newly-added file.
    subprocess.run(["git", "-C", str(repo), "reset", "-q", "--", *paths],
                   capture_output=True, text=True)
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
