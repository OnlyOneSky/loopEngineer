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


class _SpyReporter:
    def __init__(self):
        self.events = []

    def run_start(self, *a): self.events.append(("run_start", a))
    def iteration_start(self, *a): self.events.append(("iteration_start", a))
    def phase(self, *a): self.events.append(("phase", a))
    def retry(self, *a): self.events.append(("retry", a))
    def finished(self, *a): self.events.append(("finished", a))


def test_reporter_narrates_converge(tmp_path):
    repo = _bank_repo(tmp_path)
    agent = MockAgent(actor_steps=[_write_decimal], security_fn=_security_fn)
    mem = Memory.create(tmp_path / "runs", "run-r", "spec.md", str(repo), "loop/run-r", Caps())
    spy = _SpyReporter()
    orchestrator.run_loop("# Landing page\n", repo, agent, Caps(), mem,
                          "constitution", tmp_path / ".wt", reporter=spy)
    kinds = [e[0] for e in spy.events]
    assert kinds[0] == "run_start"
    # all five phase letters were reported in order on the converging attempt
    phase_letters = [e[1][0] for e in spy.events if e[0] == "phase"]
    assert phase_letters == ["A", "B", "C", "D", "E"]
    assert spy.events[-1][0] == "finished"
    assert spy.events[-1][1][0] == "converged"
    # spec summary passed to run_start is the first line, hash-stripped
    assert spy.events[0][1][1] == "Landing page"


def test_reporter_narrates_retry_then_escalation(tmp_path):
    repo = _bank_repo(tmp_path)
    agent = MockAgent(actor_steps=[_write_gt] * 2)   # boundary bug every attempt
    caps = Caps(max_iterations=2)
    mem = Memory.create(tmp_path / "runs", "run-e", "spec.md", str(repo), "loop/run-e", caps)
    spy = _SpyReporter()
    orchestrator.run_loop("spec", repo, agent, caps, mem,
                          "constitution", tmp_path / ".wt", reporter=spy)
    assert [e for e in spy.events if e[0] == "retry"]         # at least one retry
    assert spy.events[-1][0] == "finished"
    assert spy.events[-1][1][0] == "escalated"
