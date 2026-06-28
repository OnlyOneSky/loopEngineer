import json
import subprocess
from pathlib import Path
from loopengine import connectors


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_x.py").write_text("def test_ok():\n    assert 1 == 1\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "init"], check=True)
    return repo


def test_run_tests_passes(tmp_path):
    repo = _init_repo(tmp_path)
    result = connectors.run_tests(repo)
    assert result["passed"] is True


def test_run_tests_fails_and_reports(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "tests" / "test_x.py").write_text("def test_bad():\n    assert 1 == 2\n")
    result = connectors.run_tests(repo)
    assert result["passed"] is False
    assert "assert" in result["summary"].lower()


def test_changed_paths_and_revert(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "tests" / "test_x.py").write_text("def test_tamper():\n    assert True\n")
    assert "tests/test_x.py" in connectors.git_changed_paths(repo)
    connectors.git_revert_paths(repo, ["tests/test_x.py"])
    assert connectors.git_changed_paths(repo) == []


def test_run_tests_leaves_worktree_clean(tmp_path):
    repo = _init_repo(tmp_path)
    connectors.run_tests(repo)
    # No __pycache__/.pytest_cache untracked artifacts left behind.
    assert connectors.git_changed_paths(repo) == []


def test_write_pr_artifact(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    path = connectors.write_pr_artifact(
        run_dir, "add limit", "diff text",
        {"verdict": "pass", "gaps": []}, {"verdict": "pass", "findings": []})
    assert path == run_dir / "pr-artifact.md"
    body = path.read_text()
    assert "add limit" in body and "diff text" in body and "verdict" in body
