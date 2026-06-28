import subprocess
from pathlib import Path
from loopengine import isolation
from loopengine.config import PROTECTED


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_x.py").write_text("def test_ok():\n    assert True\n")
    (repo / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "init"], check=True)
    return repo


def test_worktree_is_isolated_checkout(tmp_path):
    repo = _init_repo(tmp_path)
    wt = isolation.create_worktree(repo, "loop/run-1", tmp_path / ".wt")
    assert (wt / "app.py").exists()
    assert wt != repo
    isolation.cleanup_worktree(repo, wt)
    assert not wt.exists()


def test_enforce_detects_and_reverts_test_tampering(tmp_path):
    repo = _init_repo(tmp_path)
    wt = isolation.create_worktree(repo, "loop/run-2", tmp_path / ".wt")
    (wt / "tests" / "test_x.py").write_text("def test_ok():\n    assert True  # weakened\n")
    (wt / "app.py").write_text("x = 2\n")  # legitimate change, must survive
    ok, reason = isolation.assert_no_protected_changes(wt, PROTECTED)
    assert ok is False
    assert "tests/test_x.py" in reason
    assert (wt / "tests" / "test_x.py").read_text() == "def test_ok():\n    assert True\n"
    assert (wt / "app.py").read_text() == "x = 2\n"


def test_enforce_allows_non_protected_changes(tmp_path):
    repo = _init_repo(tmp_path)
    wt = isolation.create_worktree(repo, "loop/run-3", tmp_path / ".wt")
    (wt / "app.py").write_text("x = 99\n")
    ok, reason = isolation.assert_no_protected_changes(wt, PROTECTED)
    assert ok is True and reason == ""
