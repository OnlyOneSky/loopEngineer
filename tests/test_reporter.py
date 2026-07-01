import io

from loopengine.reporter import (ConsoleReporter, MultiReporter, NullReporter,
                                  SlackReporter)


def test_console_reporter_writes_phase_lines():
    buf = io.StringIO()
    r = ConsoleReporter(out=buf)
    r.run_start("run-1", "landing page", "MockAgent", 6)
    r.iteration_start(1, 6, 0)
    r.phase("A", "Actor", "info", "3 path(s) changed")
    r.phase("C", "Tests", "ok", "5 passed")
    r.finished("converged", "all gates passed", "runs/run-1/pr-artifact.md")
    out = buf.getvalue()
    assert "landing page" in out and "MockAgent" in out and "cap: 6" in out
    assert "Iteration 1/6" in out
    assert "A Actor" in out and "3 path(s) changed" in out
    assert "✓" in out and "5 passed" in out
    assert "CONVERGED" in out and "runs/run-1/pr-artifact.md" in out


def test_console_reporter_shows_retry_and_escalation():
    buf = io.StringIO()
    r = ConsoleReporter(out=buf)
    r.iteration_start(1, 3, 0)
    r.phase("B", "Enforce", "fail", "Actor modified protected files: ['tests/x.py']")
    r.retry("Actor modified protected files: ['tests/x.py']\nmore detail")
    r.finished("escalated", "iteration cap", None)
    out = buf.getvalue()
    assert "✗" in out
    assert "retry —" in out and "more detail" not in out  # only the first line
    assert "ESCALATED" in out


class _FakePoster:
    def __init__(self):
        self.calls = []       # list of (text, thread_ts)
        self._n = 0

    def post(self, text, thread_ts=None):
        self.calls.append((text, thread_ts))
        self._n += 1
        return thread_ts or f"ts-{self._n}"


def test_slack_reporter_threads_under_the_root():
    poster = _FakePoster()
    r = SlackReporter(poster)
    r.run_start("run-1", "landing page", "ClaudeAgent", 6)
    root_ts = poster.calls[0][1]
    assert root_ts is None                              # root posts with no thread
    r.iteration_start(1, 6, 0)
    r.phase("A", "Actor", "info", "3 changed")
    r.phase("C", "Tests", "fail", "1 failed")
    r.retry("tests failed: 1 failed")
    # the iteration reply threads under the captured root ts
    assert poster.calls[1][1] == "ts-1"
    assert "Iteration 1/6" in poster.calls[1][0]
    assert "1 failed" in poster.calls[1][0] and "retry" in poster.calls[1][0]


def test_slack_reporter_converge_posts_verdict_with_artifact():
    poster = _FakePoster()
    r = SlackReporter(poster)
    r.run_start("run-1", "spec", "MockAgent", 6)
    r.iteration_start(2, 6, 5)
    r.phase("E", "Security", "ok", "constitution satisfied")
    r.finished("converged", "all gates passed", "runs/run-1/pr-artifact.md")
    last = poster.calls[-1][0]
    assert "Converged" in last and "pr-artifact.md" in last


def test_slack_reporter_escalation_after_retry_does_not_repeat_phases():
    poster = _FakePoster()
    r = SlackReporter(poster)
    r.run_start("run-1", "spec", "MockAgent", 3)
    r.iteration_start(3, 3, 9)
    r.phase("C", "Tests", "fail", "1 failed")
    r.retry("tests failed")            # flushes + clears the buffer
    r.finished("escalated", "iteration cap", None)
    assert "Escalated" in poster.calls[-1][0]
    assert "C Tests" not in poster.calls[-1][0]   # not repeated in the escalation post


def test_multi_reporter_fans_out():
    a, b = _RecordingReporter(), _RecordingReporter()
    r = MultiReporter([a, b, None])    # None is tolerated
    r.run_start("r", "s", "MockAgent", 6)
    r.phase("A", "Actor", "info", "")
    r.finished("converged", "ok", None)
    for rec in (a, b):
        assert rec.events == ["run_start", "phase", "finished"]


def test_null_reporter_accepts_everything():
    r = NullReporter()
    r.run_start("r", "s", "a", 6)
    r.iteration_start(1, 6, 0)
    r.phase("A", "Actor", "info")
    r.retry("x")
    r.finished("converged", "ok", None)   # no exception = pass


class _RecordingReporter:
    def __init__(self):
        self.events = []

    def run_start(self, *a, **k): self.events.append("run_start")
    def iteration_start(self, *a, **k): self.events.append("iteration_start")
    def phase(self, *a, **k): self.events.append("phase")
    def retry(self, *a, **k): self.events.append("retry")
    def finished(self, *a, **k): self.events.append("finished")
