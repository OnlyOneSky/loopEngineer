import shutil
from pathlib import Path
from loopengine import trigger, config
from loopengine.agents import MockAgent
from loopengine.config import Caps, MAX_ITERATIONS


def _decimal_actor(wt: Path):
    (wt / "bankapp" / "transfer.py").write_text(
        "from decimal import Decimal\n"
        "class LimitExceeded(Exception):\n    pass\n\n"
        "def transfer(amount, daily_total, tier_limit, audit_log):\n"
        "    if daily_total + amount <= tier_limit:\n"
        "        audit_log.append(('transfer', amount)); return 'OK'\n"
        "    audit_log.append(('blocked', amount)); raise LimitExceeded()\n")


def test_run_against_demo_repo_converges(tmp_path):
    # Copy the committed demo repo into a temp dir so the test doesn't dirty it.
    demo_src = config.ROOT / "demo" / "bankapp"
    repo = tmp_path / "bankapp"
    shutil.copytree(demo_src, repo)
    agent = MockAgent(actor_steps=[_decimal_actor])
    state = trigger.run(demo_src / "specs" / "transfer-limit.md", repo,
                        agent=agent, caps=Caps(),
                        runs_dir=tmp_path / "runs", worktree_root=tmp_path / ".wt")
    assert state["status"] == "converged"


def test_caps_from_args_clamps_to_ceiling():
    assert trigger._caps_from_args(None).max_iterations == MAX_ITERATIONS
    assert trigger._caps_from_args(3).max_iterations == 3
    assert trigger._caps_from_args(99).max_iterations == MAX_ITERATIONS   # clamped down
    assert trigger._caps_from_args(0).max_iterations == 1                  # floored up


def test_resolve_constitution_prefers_repo_then_explicit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    # falls back to the default skills constitution when the repo carries none
    assert "Engineering Constitution" in trigger._resolve_constitution(repo, None)
    # a repo-local constitution.md is picked up automatically
    (repo / "constitution.md").write_text("# Web Constitution\nlocal rules\n")
    assert "Web Constitution" in trigger._resolve_constitution(repo, None)
    # an explicit --constitution path wins over the repo-local one
    explicit = tmp_path / "other.md"
    explicit.write_text("# Explicit\n")
    assert "Explicit" in trigger._resolve_constitution(repo, explicit)


_VALID_INDEX = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<title>Loopwear</title>
<link rel="stylesheet" href="styles.css" /></head>
<body>
<nav><a href="index.html">Home</a> <a href="#about">About</a> <a href="#contact">Contact</a></nav>
<header><h1>Loopwear</h1></header>
<main><p>Clothes that go around.</p></main>
<footer>© 2026 Loopwear</footer>
</body></html>
"""


def _website_actor(wt: Path):
    (wt / "index.html").write_text(_VALID_INDEX, encoding="utf-8")
    (wt / "styles.css").write_text("body { font-family: sans-serif; }\n", encoding="utf-8")


def test_website_scenario_converges_in_one_iteration(tmp_path):
    demo_src = config.ROOT / "demo" / "website"
    repo = tmp_path / "website"
    shutil.copytree(demo_src, repo)
    agent = MockAgent(actor_steps=[_website_actor])
    state = trigger.run(demo_src / "specs" / "landing-page.md", repo,
                        agent=agent, caps=Caps(),
                        runs_dir=tmp_path / "runs", worktree_root=tmp_path / ".wt")
    assert state["status"] == "converged"
    assert len(state["iterations"]) == 1


def _refund_actor(wt: Path):
    # A best-effort implementation; it can never satisfy both contradictory tests.
    (wt / "pricing.py").write_text(
        "from decimal import Decimal\n"
        "class RefundDenied(Exception):\n    pass\n\n"
        "def refund(amount, limit):\n"
        "    if amount <= limit:\n        return 'REFUNDED'\n"
        "    raise RefundDenied()\n", encoding="utf-8")


def test_impossible_scenario_escalates_at_cap(tmp_path):
    demo_src = config.ROOT / "demo" / "impossible"
    repo = tmp_path / "impossible"
    shutil.copytree(demo_src, repo)
    caps = Caps(max_iterations=2)
    agent = MockAgent(actor_steps=[_refund_actor, _refund_actor])
    state = trigger.run(demo_src / "specs" / "instant-refund.md", repo,
                        agent=agent, caps=caps,
                        runs_dir=tmp_path / "runs", worktree_root=tmp_path / ".wt")
    assert state["status"] == "escalated"
    assert len(state["iterations"]) == 2
    assert "Tests failed" in state["iterations"][-1]["last_error"]


_GREENFIELD_TESTS = (
    "from decimal import Decimal\n"
    "import pytest\n"
    "from transferapp.transfer import transfer, LimitExceeded\n\n\n"
    "def test_ac1_under_limit_allowed():\n"
    "    assert transfer(Decimal('10'), Decimal('0'), Decimal('100'), []) == 'OK'\n\n\n"
    "def test_ac2_over_limit_blocked():\n"
    "    with pytest.raises(LimitExceeded):\n"
    "        transfer(Decimal('60'), Decimal('50'), Decimal('100'), [])\n\n\n"
    "def test_ac3_exact_equal_allowed():\n"
    "    assert transfer(Decimal('50'), Decimal('50'), Decimal('100'), []) == 'OK'\n\n\n"
    "def test_ac4_audit_trail():\n"
    "    log = []\n"
    "    with pytest.raises(LimitExceeded):\n"
    "        transfer(Decimal('60'), Decimal('50'), Decimal('100'), log)\n"
    "    assert ('blocked', Decimal('60')) in log\n"
)


def _author_greenfield(wt: Path):
    (wt / "tests" / "acceptance").mkdir(parents=True)
    (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(_GREENFIELD_TESTS)


def _implement_greenfield(wt: Path):
    (wt / "transferapp" / "transfer.py").write_text(
        "from decimal import Decimal\n\n\n"
        "class LimitExceeded(Exception):\n    pass\n\n\n"
        "def transfer(amount, daily_total, tier_limit, audit_log):\n"
        "    if daily_total + amount <= tier_limit:\n"
        "        audit_log.append(('transfer', amount)); return 'OK'\n"
        "    audit_log.append(('blocked', amount)); raise LimitExceeded()\n")


def test_synthesize_end_to_end_converges(tmp_path):
    demo_src = config.ROOT / "demo" / "greenfield-transfer"
    repo = tmp_path / "greenfield"
    shutil.copytree(demo_src, repo)
    agent = MockAgent(actor_steps=[_implement_greenfield],
                      test_author_steps=[_author_greenfield])
    state = trigger.run(demo_src / "specs" / "daily-limit.md", repo,
                        agent=agent, caps=Caps(), gate_mode="synthesize",
                        runs_dir=tmp_path / "runs", worktree_root=tmp_path / ".wt")
    assert state["status"] == "converged"
    assert state["gate"]["ok"] is True
    assert state["gate"]["ref"].startswith("gate/")
    # the PR diff is implementation-only: gate tests are listed in memory,
    # not diffed in the artifact
    artifact = Path(state["result"]["artifact"]).read_text()
    assert "transfer.py" in artifact
    assert "test_daily_limit" not in artifact


def test_synthesize_gate_failure_escalates_without_looping(tmp_path):
    demo_src = config.ROOT / "demo" / "greenfield-transfer"
    repo = tmp_path / "greenfield2"
    shutil.copytree(demo_src, repo)

    def vacuous(wt: Path):
        (wt / "tests" / "acceptance").mkdir(parents=True, exist_ok=True)
        (wt / "tests" / "acceptance" / "test_daily_limit.py").write_text(
            "def test_ac1():\n    assert True\n")

    agent = MockAgent(actor_steps=[], test_author_steps=[vacuous, vacuous, vacuous])
    state = trigger.run(demo_src / "specs" / "daily-limit.md", repo,
                        agent=agent, caps=Caps(), gate_mode="synthesize",
                        runs_dir=tmp_path / "runs", worktree_root=tmp_path / ".wt")
    assert state["status"] == "escalated"
    assert state["result"]["outcome"].startswith("gate:")
    assert state["iterations"] == []                    # the loop never started


def test_cli_rejects_unknown_gate_mode():
    import pytest
    # argparse exits (code 2) on a value outside choices, before run() is reached
    with pytest.raises(SystemExit):
        trigger.main(["run", "--spec", "s", "--repo", "r", "--gate", "bogus"])
