"""Phase 0 — gate synthesis. An independent test-author agent turns the
human-approved spec into the deterministic acceptance gate, verified on the
UNTOUCHED code and frozen onto a gate/<run-id> branch BEFORE the actor runs.

The maker/checker split extends one layer up: the actor is graded against
tests it did not write and cannot edit. Fail closed: no valid gate -> the run
escalates and the loop never starts. The target repo's main is never touched.
"""
import re
from pathlib import Path

from . import connectors, isolation
from .config import GATE_MAX_ATTEMPTS
from .memory import Memory
from .reporter import NullReporter


def synthesize_gate(spec_text: str, repo: Path, agent, memory: Memory,
                    worktree_root: Path, reporter=None,
                    max_attempts: int = GATE_MAX_ATTEMPTS) -> dict:
    reporter = reporter or NullReporter()
    branch = f"gate/{memory.state['run_id']}"
    worktree = isolation.create_worktree(repo, branch, worktree_root)
    last_error = ""
    try:
        # Precondition: the existing suite must be green on the untouched code
        # (exit 5 = no tests yet, fine for greenfield).
        baseline = connectors.run_tests(worktree)
        if baseline["returncode"] not in (0, 5):
            return _finish(memory, reporter,
                           f"existing suite is red on the untouched repo:\n"
                           f"{baseline['summary'][-800:]}")

        for attempt in range(1, max_attempts + 1):
            reporter.gate("info", f"synthesizing acceptance gate "
                                  f"(attempt {attempt}/{max_attempts})")
            agent.test_author(spec_text, last_error, worktree)
            author_dir = connectors.gate_config(worktree).get("author_dir", "tests/")
            kept, reverted = isolation.enforce_author_scope(worktree, (author_dir,))
            if reverted:
                reporter.gate("info", f"reverted {len(reverted)} out-of-scope write(s)")

            problem, red = _verify(worktree, spec_text, kept)
            if problem:
                # Reset to the frozen baseline so a bad attempt's files cannot
                # poison the next one (git clean removes the untracked kept files).
                connectors.git_revert_paths(worktree, kept)
                last_error = problem
                reporter.gate("fail", _first(problem))
                continue

            connectors.git_commit_all(
                worktree, f"gate: acceptance tests ({memory.state['run_id']})")
            info = {"ok": True, "ref": branch, "tests": kept,
                    "red_on_baseline": sorted(red), "attempts": attempt}
            memory.record_gate(info)
            reporter.gate("ok", f"frozen: {len(kept)} test file(s) · "
                                f"{len(red)} red on baseline → {branch}")
            return info

        return _finish(memory, reporter,
                       f"no valid gate after {max_attempts} attempts; "
                       f"last: {_first(last_error)}")
    finally:
        isolation.cleanup_worktree(repo, worktree)


def _verify(worktree: Path, spec_text: str,
            new_files: list[str]) -> tuple[str | None, set[str]]:
    """The mechanical gate-on-the-gate. Returns (problem, red_test_ids)."""
    if not new_files:
        return "no new test files were written in the gate author directory", set()
    run1 = connectors.run_tests(worktree)
    if run1.get("custom"):
        # Framework-agnostic path (loop.toml test_command): exit-code semantics.
        # We cannot attribute individual failures to files, so the red/vacuity
        # checks are coarser; AC coverage below still applies.
        run2 = connectors.run_tests(worktree)      # determinism: run twice
        if run1["returncode"] != run2["returncode"]:
            return ("the gate is nondeterministic: two identical baseline runs "
                    f"exited {run1['returncode']} vs {run2['returncode']}"), set()
        if run1["returncode"] == 0:
            return ("vacuous gate: the suite passes on the UNIMPLEMENTED code — "
                    "the new tests do not exercise the new behavior"), set()
        missing = _uncovered_acs(spec_text, worktree, new_files)
        if missing:
            return "acceptance criteria without a mapped test: " + ", ".join(missing), set()
        return None, {f"suite:exit-{run1['returncode']}"}
    if run1["returncode"] in (2, 3, 4):
        return f"the test suite fails to load:\n{run1['summary'][-800:]}", set()
    if run1["returncode"] == 5:
        return "pytest collected no tests from the new files", set()
    run2 = connectors.run_tests(worktree)          # determinism: run twice
    fail1, fail2 = _failing_ids(run1["summary"]), _failing_ids(run2["summary"])
    if fail1 != fail2:
        return ("the gate is nondeterministic: two identical baseline runs "
                f"disagree on {sorted(fail1 ^ fail2)}"), set()
    if not fail1:
        return ("vacuous gate: every test passes on the UNIMPLEMENTED code — "
                "the tests do not exercise the new behavior"), set()
    outside = {t for t in fail1
               if not any(t.startswith(f) for f in new_files)}
    if outside:
        return f"the new tests break the existing suite: {sorted(outside)}", set()
    missing = _uncovered_acs(spec_text, worktree, new_files)
    if missing:
        return "acceptance criteria without a mapped test: " + ", ".join(missing), set()
    return None, fail1


def _failing_ids(summary: str) -> set[str]:
    """Parse 'FAILED tests/x.py::test_y - ...' lines from pytest -q output."""
    ids = set()
    for line in summary.splitlines():
        line = line.strip()
        if line.startswith(("FAILED ", "ERROR ")):
            ids.add(line.split(" ", 2)[1])
    return ids


def _uncovered_acs(spec_text: str, worktree: Path, new_files: list[str]) -> list[str]:
    """Every AC-N in the spec must appear (as ac-n / ac_n / acn, any case) in
    the generated tests' names or comments. Skipped when the spec has no ids."""
    acs = sorted(set(re.findall(r"AC-\d+", spec_text)))
    if not acs:
        return []
    corpus = " ".join((worktree / f).read_text(encoding="utf-8")
                      for f in new_files).lower()
    corpus = corpus.replace("_", "").replace("-", "")
    return [ac for ac in acs if ac.lower().replace("-", "") not in corpus]


def _finish(memory: Memory, reporter, reason: str) -> dict:
    info = {"ok": False, "reason": reason}
    memory.record_gate(info)
    reporter.gate("fail", _first(reason))
    return info


def _first(text: str) -> str:
    text = (text or "").strip()
    return text.splitlines()[0] if text else ""
