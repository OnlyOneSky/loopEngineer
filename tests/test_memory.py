import json
from loopengine.config import Caps
from loopengine.memory import Memory


def test_create_writes_initial_state(tmp_path):
    m = Memory.create(tmp_path, "run-1", "spec.md", "repo", "loop/run-1", Caps())
    assert m.path == tmp_path / "run-1" / "state.json"
    on_disk = json.loads(m.path.read_text())
    assert on_disk["run_id"] == "run-1"
    assert on_disk["status"] == "running"
    assert on_disk["caps"] == {"max_iterations": 6, "max_wall_seconds": 1200}
    assert on_disk["iterations"] == []


def test_iteration_lifecycle_persists(tmp_path):
    m = Memory.create(tmp_path, "run-2", "spec.md", "repo", "loop/run-2", Caps())
    m.add_iteration(1, elapsed_s=0)
    m.update_iteration(tests={"passed": False, "summary": "boom"}, last_error="Tests failed: boom")
    on_disk = json.loads(m.path.read_text())
    assert on_disk["iterations"][0]["n"] == 1
    assert on_disk["iterations"][0]["tests"]["passed"] is False
    assert on_disk["iterations"][0]["last_error"] == "Tests failed: boom"


def test_finish_sets_result(tmp_path):
    m = Memory.create(tmp_path, "run-3", "spec.md", "repo", "loop/run-3", Caps())
    m.finish("converged", "all gates passed", artifact="runs/run-3/pr-artifact.md")
    on_disk = json.loads(m.path.read_text())
    assert on_disk["status"] == "converged"
    assert on_disk["result"] == {"outcome": "all gates passed", "artifact": "runs/run-3/pr-artifact.md"}
