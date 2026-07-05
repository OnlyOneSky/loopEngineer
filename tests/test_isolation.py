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


def test_enforce_detects_untracked_protected_addition(tmp_path):
    repo = _init_repo(tmp_path)
    wt = isolation.create_worktree(repo, "loop/run-untracked", tmp_path / ".wt")
    (wt / "tests" / "test_new.py").write_text("def test_sneaky():\n    assert True\n")
    (wt / "feature.py").write_text("y = 1\n")  # legit untracked, must survive
    ok, reason = isolation.assert_no_protected_changes(wt, PROTECTED)
    assert ok is False
    assert "tests/test_new.py" in reason
    assert not (wt / "tests" / "test_new.py").exists()  # reverted
    assert (wt / "feature.py").read_text() == "y = 1\n"  # survived


def test_enforce_reverts_staged_protected_tamper(tmp_path):
    repo = _init_repo(tmp_path)
    wt = isolation.create_worktree(repo, "loop/run-staged", tmp_path / ".wt")
    (wt / "tests" / "test_x.py").write_text("def test_ok():\n    assert True  # weakened\n")
    subprocess.run(["git", "-C", str(wt), "add", "tests/test_x.py"], check=True)  # STAGE the tamper
    ok, reason = isolation.assert_no_protected_changes(wt, PROTECTED)
    assert ok is False
    assert "tests/test_x.py" in reason
    # Reverted despite being staged: content back to original, nothing staged.
    assert (wt / "tests" / "test_x.py").read_text() == "def test_ok():\n    assert True\n"
    staged = subprocess.run(["git", "-C", str(wt), "diff", "--cached", "--name-only"],
                            capture_output=True, text=True).stdout
    assert "tests/test_x.py" not in staged


def test_enforce_removes_staged_new_protected_file(tmp_path):
    repo = _init_repo(tmp_path)
    wt = isolation.create_worktree(repo, "loop/run-stagednew", tmp_path / ".wt")
    (wt / "tests" / "test_evil.py").write_text("def test_evil():\n    assert True\n")
    subprocess.run(["git", "-C", str(wt), "add", "tests/test_evil.py"], check=True)  # stage a NEW file
    ok, reason = isolation.assert_no_protected_changes(wt, PROTECTED)
    assert ok is False
    assert "tests/test_evil.py" in reason
    assert not (wt / "tests" / "test_evil.py").exists()  # removed


from loopengine import config


def _mini_repo(tmp_path):
    repo = tmp_path / "mini"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
    (repo / "AGENTS.md").write_text("# conventions\n")
    (repo / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "init"], check=True)
    return repo


def test_conventions_files_are_protected(tmp_path):
    assert "AGENTS.md" in config.PROTECTED and "CLAUDE.md" in config.PROTECTED
    repo = _mini_repo(tmp_path)
    (repo / "AGENTS.md").write_text("# weakened by the actor\n")
    ok, why = isolation.assert_no_protected_changes(repo, config.PROTECTED)
    assert ok is False and "AGENTS.md" in why
    # and the tamper was reverted
    assert (repo / "AGENTS.md").read_text() == "# conventions\n"


def test_gate_max_attempts_exists():
    assert config.GATE_MAX_ATTEMPTS == 3
