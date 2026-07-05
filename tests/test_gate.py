import subprocess
from pathlib import Path

from loopengine import gate
from loopengine.agents import MockAgent
from loopengine.config import Caps
from loopengine.memory import Memory

# A greenfield-style repo: incomplete implementation, NO tests/.
STUB = (
    "from decimal import Decimal\n\n\n"
    "class LimitExceeded(Exception):\n    pass\n\n\n"
    "def transfer(amount, daily_total, tier_limit, audit_log):\n"
    "    raise NotImplementedError\n"
)

SPEC = (
    "# Feature: daily transfer limit\n\n"
    "## Acceptance criteria\n"
    "- AC-1: under-limit transfers return 'OK'.\n"
    "- AC-2: over-limit transfers raise LimitExceeded.\n"
)

GOOD_TESTS = (
    "from decimal import Decimal\n"
    "import pytest\n"
    "from transferapp.transfer import transfer, LimitExceeded\n\n\n"
    "def test_ac1_under_limit_allowed():\n"
    "    assert transfer(Decimal('10'), Decimal('0'), Decimal('100'), []) == 'OK'\n\n\n"
    "def test_ac2_over_limit_blocked():\n"
    "    with pytest.raises(LimitExceeded):\n"
    "        transfer(Decimal('60'), Decimal('50'), Decimal('100'), [])\n"
)


def _greenfield_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "greenfield"
    (repo / "transferapp").mkdir(parents=True)
    (repo / "transferapp" / "__init__.py").write_text("")
    (repo / "transferapp" / "transfer.py").write_text(STUB)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "init"], check=True)
    return repo


def _write_good_tests(wt: Path):
    (wt / "tests" / "acceptance").mkdir(parents=True, exist_ok=True)
    (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(GOOD_TESTS)


def _mem(tmp_path, repo, run_id="run-g1"):
    return Memory.create(tmp_path / "runs", run_id, "spec.md", str(repo),
                         f"loop/{run_id}", Caps())


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def test_synthesize_gate_happy_path(tmp_path):
    repo = _greenfield_repo(tmp_path)
    main_before = _git(repo, "rev-parse", "main").stdout.strip()
    agent = MockAgent(actor_steps=[], test_author_steps=[_write_good_tests])
    mem = _mem(tmp_path, repo)

    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt")

    assert result["ok"] is True
    assert result["ref"] == "gate/run-g1"
    assert result["tests"] == ["tests/acceptance/test_daily_limit.py"]
    assert len(result["red_on_baseline"]) == 2          # both tests red on the stub
    assert result["attempts"] == 1
    # the gate is committed on its branch, and main is untouched
    show = _git(repo, "show", "gate/run-g1:tests/acceptance/test_daily_limit.py")
    assert "test_ac1_under_limit_allowed" in show.stdout
    assert _git(repo, "rev-parse", "main").stdout.strip() == main_before
    # recorded in memory
    assert mem.state["gate"]["ok"] is True


def _write_vacuous_tests(wt: Path):
    (wt / "tests" / "acceptance").mkdir(parents=True, exist_ok=True)
    (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(
        "def test_ac1_nothing():\n    assert True\n\n"
        "def test_ac2_nothing():\n    assert True\n")


def _write_broken_tests(wt: Path):
    (wt / "tests" / "acceptance").mkdir(parents=True, exist_ok=True)
    (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(
        "def test_ac1_broken(:\n    pass\n")          # syntax error


def _write_ac1_only(wt: Path):
    (wt / "tests" / "acceptance").mkdir(parents=True, exist_ok=True)
    (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(
        "from decimal import Decimal\n"
        "from transferapp.transfer import transfer\n\n"
        "def test_ac1_under_limit_allowed():\n"
        "    assert transfer(Decimal('10'), Decimal('0'), Decimal('100'), []) == 'OK'\n")


def _write_flip_test(wt: Path):
    (wt / "tests" / "acceptance").mkdir(parents=True, exist_ok=True)
    (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(
        "from pathlib import Path\n\n"
        "def test_ac1_flip():\n"
        "    m = Path('flip.marker')\n"
        "    existed = m.exists()\n"
        "    m.touch()\n"
        "    assert existed\n\n"                       # run 1 fails, run 2 passes
        "def test_ac2_anchor():\n    assert False\n")


def _write_tests_and_implementation(wt: Path):
    _write_good_tests(wt)
    (wt / "transferapp" / "transfer.py").write_text("SNEAKY = True\n")


def test_vacuous_gate_retries_then_escalates(tmp_path):
    repo = _greenfield_repo(tmp_path)
    agent = MockAgent(actor_steps=[],
                      test_author_steps=[_write_vacuous_tests, _write_vacuous_tests])
    mem = _mem(tmp_path, repo, "run-vac")
    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt",
                                  max_attempts=2)
    assert result["ok"] is False
    assert "vacuous" in result["reason"]
    assert mem.state["gate"]["ok"] is False


def test_unloadable_suite_is_a_failed_attempt(tmp_path):
    repo = _greenfield_repo(tmp_path)
    agent = MockAgent(actor_steps=[],
                      test_author_steps=[_write_broken_tests, _write_good_tests])
    mem = _mem(tmp_path, repo, "run-load")
    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt")
    assert result["ok"] is True and result["attempts"] == 2   # recovered on retry


def test_missing_ac_coverage_names_the_gap(tmp_path):
    repo = _greenfield_repo(tmp_path)
    agent = MockAgent(actor_steps=[], test_author_steps=[_write_ac1_only])
    mem = _mem(tmp_path, repo, "run-ac")
    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt",
                                  max_attempts=1)
    assert result["ok"] is False
    assert "AC-2" in result["reason"]


def test_nondeterministic_gate_is_rejected(tmp_path):
    repo = _greenfield_repo(tmp_path)
    agent = MockAgent(actor_steps=[], test_author_steps=[_write_flip_test])
    mem = _mem(tmp_path, repo, "run-flip")
    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt",
                                  max_attempts=1)
    assert result["ok"] is False
    assert "nondeterministic" in result["reason"]


def test_author_implementation_writes_are_reverted(tmp_path):
    repo = _greenfield_repo(tmp_path)
    agent = MockAgent(actor_steps=[],
                      test_author_steps=[_write_tests_and_implementation])
    mem = _mem(tmp_path, repo, "run-scope")
    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt")
    assert result["ok"] is True                        # tests kept, impl reverted
    show = subprocess.run(["git", "-C", str(repo), "show",
                           "gate/run-scope:transferapp/transfer.py"],
                          capture_output=True, text=True).stdout
    assert "SNEAKY" not in show and "NotImplementedError" in show


def test_red_existing_suite_escalates_before_authoring(tmp_path):
    repo = _greenfield_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_old.py").write_text("def test_old():\n    assert False\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "red suite"], check=True)
    agent = MockAgent(actor_steps=[], test_author_steps=[])   # never called
    mem = _mem(tmp_path, repo, "run-red")
    result = gate.synthesize_gate(SPEC, repo, agent, mem, tmp_path / ".wt")
    assert result["ok"] is False
    assert "existing suite is red" in result["reason"]


from loopengine import config


def test_greenfield_demo_shape():
    demo = config.ROOT / "demo" / "greenfield-transfer"
    assert (demo / "AGENTS.md").exists()
    assert (demo / "specs" / "daily-limit.md").exists()
    assert not (demo / "tests").exists()               # the loop authors the gate
    spec = (demo / "specs" / "daily-limit.md").read_text()
    assert "Stack & interface" in spec
    assert all(f"AC-{n}" in spec for n in (1, 2, 3, 4))
    assert "NotImplementedError" in (demo / "transferapp" / "transfer.py").read_text()
