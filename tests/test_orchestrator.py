import subprocess
from pathlib import Path
from loopengine import orchestrator, connectors
from loopengine.agents import MockAgent
from loopengine.config import Caps, PROTECTED
from loopengine.memory import Memory


def _bank_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "bank"
    (repo / "bankapp").mkdir(parents=True)
    (repo / "bankapp" / "__init__.py").write_text("")
    (repo / "bankapp" / "transfer.py").write_text(
        "class LimitExceeded(Exception):\n    pass\n\n"
        "def transfer(amount, daily_total, tier_limit, audit_log):\n"
        "    audit_log.append(('transfer', amount))\n    return 'OK'\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_transfer.py").write_text(
        "from decimal import Decimal\nimport pytest\n"
        "from bankapp.transfer import transfer, LimitExceeded\n\n"
        "def test_under_limit_allowed():\n"
        "    assert transfer(Decimal('10'), Decimal('0'), Decimal('100'), []) == 'OK'\n\n"
        "def test_exact_equal_boundary_allowed():\n"
        "    assert transfer(Decimal('50'), Decimal('50'), Decimal('100'), []) == 'OK'\n\n"
        "def test_over_limit_blocked():\n"
        "    with pytest.raises(LimitExceeded):\n"
        "        transfer(Decimal('60'), Decimal('50'), Decimal('100'), [])\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c",
                    "-c", "user.name=t", "commit", "-q", "-m", "init"], check=True)
    return repo


# Actor step writers (simulate what Codex would edit on disk).
def _write_gt(wt: Path):  # uses '>' — fails the exact-equal boundary test
    (wt / "bankapp" / "transfer.py").write_text(
        "from decimal import Decimal\n"
        "class LimitExceeded(Exception):\n    pass\n\n"
        "def transfer(amount, daily_total, tier_limit, audit_log):\n"
        "    if daily_total + amount > tier_limit:\n"
        "        audit_log.append(('transfer', amount)); return 'OK'\n"
        "    audit_log.append(('blocked', amount)); raise LimitExceeded()\n")


def _write_float(wt: Path):  # passes tests but uses float -> §1 violation
    (wt / "bankapp" / "transfer.py").write_text(
        "class LimitExceeded(Exception):\n    pass\n\n"
        "def transfer(amount, daily_total, tier_limit, audit_log):\n"
        "    if float(daily_total) + float(amount) <= float(tier_limit):\n"
        "        audit_log.append(('transfer', amount)); return 'OK'\n"
        "    audit_log.append(('blocked', amount)); raise LimitExceeded()\n")


def _write_decimal(wt: Path):  # passes tests AND satisfies §1
    (wt / "bankapp" / "transfer.py").write_text(
        "from decimal import Decimal\n"
        "class LimitExceeded(Exception):\n    pass\n\n"
        "def transfer(amount, daily_total, tier_limit, audit_log):\n"
        "    if daily_total + amount <= tier_limit:\n"
        "        audit_log.append(('transfer', amount)); return 'OK'\n"
        "    audit_log.append(('blocked', amount)); raise LimitExceeded()\n")


def _security_fn(con, diff):
    return ({"verdict": "fail", "findings": [{"clause": "§1", "status": "violated",
                                              "evidence": "float()"}]}
            if "float(" in diff else {"verdict": "pass", "findings": []})


def test_three_attempt_narrative_converges(tmp_path):
    repo = _bank_repo(tmp_path)
    agent = MockAgent(actor_steps=[_write_gt, _write_float, _write_decimal],
                      security_fn=_security_fn)
    mem = Memory.create(tmp_path / "runs", "run-x", "spec.md", str(repo), "loop/run-x", Caps())
    state = orchestrator.run_loop("spec text", repo, agent, Caps(), mem,
                                  "constitution", tmp_path / ".wt")
    assert state["status"] == "converged"
    iters = state["iterations"]
    assert iters[0]["tests"]["passed"] is False          # attempt 1: boundary fail
    assert iters[1]["security"]["verdict"] == "fail"     # attempt 2: float §1
    assert iters[2]["security"]["verdict"] == "pass"     # attempt 3: decimal
    assert (Path(state["result"]["artifact"])).exists()


def test_escalates_on_iteration_cap(tmp_path):
    repo = _bank_repo(tmp_path)
    # Actor never fixes the boundary bug -> tests fail every attempt.
    agent = MockAgent(actor_steps=[_write_gt] * 3)
    caps = Caps(max_iterations=3)
    mem = Memory.create(tmp_path / "runs", "run-y", "spec.md", str(repo), "loop/run-y", caps)
    state = orchestrator.run_loop("spec text", repo, agent, caps, mem,
                                  "constitution", tmp_path / ".wt")
    assert state["status"] == "escalated"
    assert len(state["iterations"]) == 3
    assert "Tests failed" in state["iterations"][-1]["last_error"]
