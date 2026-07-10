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


def test_run_tests_reports_returncode(tmp_path):
    # exit 5: a repo with no tests at all
    empty = tmp_path / "empty"
    empty.mkdir()
    res = connectors.run_tests(empty)
    assert res["returncode"] == 5 and res["passed"] is False

    # exit 0: one passing test
    ok = tmp_path / "ok"
    (ok / "tests").mkdir(parents=True)
    (ok / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    res = connectors.run_tests(ok)
    assert res["returncode"] == 0 and res["passed"] is True

    # exit 1: one failing test
    bad = tmp_path / "bad"
    (bad / "tests").mkdir(parents=True)
    (bad / "tests" / "test_bad.py").write_text("def test_bad():\n    assert False\n")
    res = connectors.run_tests(bad)
    assert res["returncode"] == 1 and res["passed"] is False


def test_gate_config_absent_is_empty(tmp_path):
    assert connectors.gate_config(tmp_path) == {}


def test_run_tests_honors_loop_toml_test_command(tmp_path):
    repo = tmp_path / "r2"
    repo.mkdir()
    (repo / "loop.toml").write_text('[gate]\ntest_command = "echo custom-runner && exit 0"\n')
    result = connectors.run_tests(repo)
    assert result["passed"] and result["custom"]
    assert "custom-runner" in result["summary"]


def test_run_tests_custom_command_failure(tmp_path):
    repo = tmp_path / "r3"
    repo.mkdir()
    (repo / "loop.toml").write_text('[gate]\ntest_command = "exit 3"\n')
    result = connectors.run_tests(repo)
    assert not result["passed"] and result["returncode"] == 3 and result["custom"]


def test_run_tests_malformed_loop_toml_falls_back_to_pytest(tmp_path):
    repo = tmp_path / "r4"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_x.py").write_text("def test_ok():\n    assert True\n")
    (repo / "loop.toml").write_text("not [ valid toml")
    result = connectors.run_tests(repo)
    assert result["passed"] and not result["custom"]
