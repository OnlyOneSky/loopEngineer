import subprocess
from pathlib import Path
from loopengine.demo import ensure_demo_repo


def test_ensure_demo_repo_is_idempotent(tmp_path):
    src = tmp_path / "bankapp"
    (src / "bankapp").mkdir(parents=True)
    (src / "bankapp" / "transfer.py").write_text("x = 1\n")
    (src / "tests").mkdir()
    (src / "tests" / "test_t.py").write_text("def test_ok():\n    assert True\n")

    repo = ensure_demo_repo(src)
    assert (repo / ".git").exists()
    head1 = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout
    ensure_demo_repo(src)  # second call must not re-init or error
    head2 = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout
    assert head1 == head2
