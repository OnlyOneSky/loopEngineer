"""Reporter — the loop's live, phase-by-phase narration for a watching human.

Separate concern from memory.py: Memory is the durable audit spine (flushed to
disk, resumable); Reporter is the *ephemeral live view*. The orchestrator calls
a Reporter at every phase boundary; WHERE that narration goes — terminal, Slack,
both, or nowhere — is a swappable sink, so the loop never depends on any one.

Status vocabulary passed to phase(): "ok" | "fail" | "info".
"""
import sys
from typing import Protocol

_GLYPH = {"ok": "✓", "fail": "✗", "info": "•"}  # ✓ ✗ •


class Reporter(Protocol):
    def run_start(self, run_id: str, spec_summary: str, agent: str, max_iterations: int) -> None: ...
    def iteration_start(self, n: int, max_n: int, elapsed_s: int) -> None: ...
    def phase(self, letter: str, name: str, status: str, detail: str = "") -> None: ...
    def retry(self, reason: str) -> None: ...
    def finished(self, status: str, outcome: str, artifact: str | None) -> None: ...


class NullReporter:
    """No-op sink — the default, so the orchestrator works with no view attached."""
    def run_start(self, *a, **k) -> None: ...
    def iteration_start(self, *a, **k) -> None: ...
    def phase(self, *a, **k) -> None: ...
    def retry(self, *a, **k) -> None: ...
    def finished(self, *a, **k) -> None: ...


class ConsoleReporter:
    """The audience's main view: one indented line per phase as it resolves."""

    def __init__(self, out=None):
        self._out = out or sys.stdout

    def _p(self, line: str = "") -> None:
        print(line, file=self._out, flush=True)

    def run_start(self, run_id, spec_summary, agent, max_iterations) -> None:
        self._p()
        self._p(f"━━━ loopEngineer · {spec_summary} · "
                f"agent: {agent} · cap: {max_iterations} ━━━")

    def iteration_start(self, n, max_n, elapsed_s) -> None:
        self._p(f"Iteration {n}/{max_n}  ({elapsed_s}s)")

    def phase(self, letter, name, status, detail="") -> None:
        glyph = _GLYPH.get(status, "•")
        tail = f"  {detail}" if detail else ""
        self._p(f"  {letter} {name:<9} {glyph}{tail}")

    def retry(self, reason) -> None:
        self._p(f"  ⇒ retry — {_first_line(reason)}")
        self._p()

    def finished(self, status, outcome, artifact) -> None:
        if status == "converged":
            self._p(f"  ⇒ CONVERGED — {outcome}")
            if artifact:
                self._p(f"     artifact: {artifact}")
        else:
            self._p(f"  ⇒ ESCALATED — {outcome}")
        self._p()


class SlackReporter:
    """Posts the status stream to Slack as one thread per run.

    Root message on run start (captures the thread ts); one threaded reply per
    iteration (its phase lines + the retry/converge/escalate verdict). Phase
    lines are buffered within an iteration and flushed when it resolves, so the
    channel gets one tidy reply per attempt rather than a line-by-line drip.
    """

    def __init__(self, poster):
        self._poster = poster          # object with .post(text, thread_ts) -> ts | None
        self._thread_ts: str | None = None
        self._buffer: list[str] = []
        self._n = self._max_n = 0

    def run_start(self, run_id, spec_summary, agent, max_iterations) -> None:
        self._thread_ts = self._poster.post(
            f"\U0001f501 *loopEngineer run started*\n"
            f"• spec: {spec_summary}\n"
            f"• agent: {agent}\n"
            f"• iteration cap: {max_iterations}", None)

    def iteration_start(self, n, max_n, elapsed_s) -> None:
        self._buffer = []
        self._n, self._max_n = n, max_n

    def phase(self, letter, name, status, detail="") -> None:
        glyph = _GLYPH.get(status, "•")
        self._buffer.append(f"{glyph} {letter} {name}" + (f" — {detail}" if detail else ""))

    def retry(self, reason) -> None:
        self._post_iteration(f"↻ retry — {_first_line(reason)}")

    def finished(self, status, outcome, artifact) -> None:
        if status == "converged":
            verdict = f"✅ *Converged* — {outcome}"
            if artifact:
                verdict += f"\nartifact: `{artifact}`"
        else:
            verdict = f"\U0001f6a8 *Escalated* — {outcome}"
        self._post_iteration(verdict)

    def _post_iteration(self, verdict: str) -> None:
        header = f"*Iteration {self._n}/{self._max_n}*\n" if self._buffer else ""
        body = ("\n".join(self._buffer) + "\n") if self._buffer else ""
        self._poster.post(f"{header}{body}{verdict}", self._thread_ts)
        self._buffer = []


class MultiReporter:
    """Fans every callback out to several reporters (e.g. console + Slack)."""

    def __init__(self, reporters):
        self._reporters = [r for r in reporters if r is not None]

    def run_start(self, *a, **k) -> None:
        for r in self._reporters:
            r.run_start(*a, **k)

    def iteration_start(self, *a, **k) -> None:
        for r in self._reporters:
            r.iteration_start(*a, **k)

    def phase(self, *a, **k) -> None:
        for r in self._reporters:
            r.phase(*a, **k)

    def retry(self, *a, **k) -> None:
        for r in self._reporters:
            r.retry(*a, **k)

    def finished(self, *a, **k) -> None:
        for r in self._reporters:
            r.finished(*a, **k)


def _first_line(text: str) -> str:
    text = (text or "").strip()
    return text.splitlines()[0] if text else ""
