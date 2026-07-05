"""Sub-agents — maker (actor) and checkers (critics).

The maker/checker split is enforced by the SANDBOX, not just the prompt: critics
run `codex exec --sandbox read-only` and physically cannot edit a file.
"""
import json
import subprocess
from pathlib import Path
from typing import Callable, Protocol

from . import skills


def _last_json_line(stdout: str) -> dict:
    """Codex emits JSONL events; the final parseable line is the agent message."""
    for line in reversed(stdout.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {}


def _extract_json(text: str) -> dict:
    """Tolerant: handles a bare object, a ```json fence, or JSON embedded in prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return {}
    return {}


class Agent(Protocol):
    def actor(self, spec: str, last_error: str, worktree: Path) -> None: ...
    def test_author(self, spec: str, last_error: str, worktree: Path) -> None: ...
    def qa_critic(self, spec: str, diff: str, test_summary: str) -> dict: ...
    def security_critic(self, constitution: str, diff: str) -> dict: ...


class CodexAgent:
    """Production agent. All model work is `codex exec`, Codex-only."""

    def actor(self, spec: str, last_error: str, worktree: Path) -> None:
        prompt = skills.prompt("actor").format(spec=spec, last_error=last_error or "(first attempt)")
        subprocess.run(
            ["codex", "exec", "--sandbox", "workspace-write", "--json",
             "--skip-git-repo-check", prompt],
            cwd=worktree, capture_output=True, text=True, timeout=600)

    def test_author(self, spec: str, last_error: str, worktree: Path) -> None:
        prompt = skills.prompt("test_author").format(
            spec=spec, last_error=last_error or "(first attempt)")
        subprocess.run(
            ["codex", "exec", "--sandbox", "workspace-write", "--json",
             "--skip-git-repo-check", prompt],
            cwd=worktree, capture_output=True, text=True, timeout=600)

    def qa_critic(self, spec: str, diff: str, test_summary: str) -> dict:
        prompt = skills.prompt("qa_critic").format(spec=spec, diff=diff, test_summary=test_summary)
        return self._read_only_json(prompt)

    def security_critic(self, constitution: str, diff: str) -> dict:
        prompt = skills.prompt("security_critic").format(constitution=constitution, diff=diff)
        return self._read_only_json(prompt)

    def _read_only_json(self, prompt: str) -> dict:
        proc = subprocess.run(
            ["codex", "exec", "--sandbox", "read-only", "--json",
             "--skip-git-repo-check", prompt],
            capture_output=True, text=True, timeout=600)
        verdict = _last_json_line(proc.stdout)
        return verdict or {"verdict": "fail", "findings": [{"evidence": "no parseable verdict"}]}


class ClaudeAgent:
    """Dev-machine agent. Real end-to-end runs via headless `claude -p`, so every
    loop step is verified with a real agent here before the Codex demo."""

    def __init__(self, model: str = "claude-opus-4-8", max_turns: int = 40):
        self.model = model
        self.max_turns = max_turns

    def actor(self, spec: str, last_error: str, worktree: Path) -> None:
        prompt = skills.prompt("actor").format(spec=spec, last_error=last_error or "(first attempt)")
        subprocess.run(
            ["claude", "-p", prompt,
             "--permission-mode", "acceptEdits",
             "--allowedTools", "Read,Edit,Write",
             "--max-turns", str(self.max_turns)],
            cwd=worktree, capture_output=True, text=True, timeout=900)

    def test_author(self, spec: str, last_error: str, worktree: Path) -> None:
        prompt = skills.prompt("test_author").format(
            spec=spec, last_error=last_error or "(first attempt)")
        subprocess.run(
            ["claude", "-p", prompt,
             "--permission-mode", "acceptEdits",
             "--allowedTools", "Read,Edit,Write",
             "--max-turns", str(self.max_turns)],
            cwd=worktree, capture_output=True, text=True, timeout=900)

    def qa_critic(self, spec: str, diff: str, test_summary: str) -> dict:
        return self._critic(skills.prompt("qa_critic").format(
            spec=spec, diff=diff, test_summary=test_summary))

    def security_critic(self, constitution: str, diff: str) -> dict:
        return self._critic(skills.prompt("security_critic").format(
            constitution=constitution, diff=diff))

    def _critic(self, prompt: str) -> dict:
        proc = subprocess.run(
            ["claude", "-p", prompt,
             "--allowedTools", "Read",
             "--output-format", "json",
             "--model", self.model],
            capture_output=True, text=True, timeout=600)
        try:
            result_text = json.loads(proc.stdout)["result"]
        except (json.JSONDecodeError, KeyError):
            result_text = proc.stdout
        return _extract_json(result_text) or {
            "verdict": "fail", "findings": [{"evidence": "no parseable verdict"}]}


class MockAgent:
    """Scriptable double so the loop is testable offline without any live agent."""

    def __init__(self, actor_steps: list[Callable[[Path], None]],
                 qa_fn: Callable[[str, str, str], dict] | None = None,
                 security_fn: Callable[[str, str], dict] | None = None,
                 test_author_steps: list[Callable[[Path], None]] | None = None):
        self._steps = list(actor_steps)
        self._author_steps = list(test_author_steps or [])
        self._qa = qa_fn or (lambda spec, diff, ts: {"verdict": "pass", "gaps": []})
        self._sec = security_fn or (lambda con, diff: {"verdict": "pass", "findings": []})

    def actor(self, spec: str, last_error: str, worktree: Path) -> None:
        self._steps.pop(0)(worktree)

    def test_author(self, spec: str, last_error: str, worktree: Path) -> None:
        self._author_steps.pop(0)(worktree)

    def qa_critic(self, spec: str, diff: str, test_summary: str) -> dict:
        return self._qa(spec, diff, test_summary)

    def security_critic(self, constitution: str, diff: str) -> dict:
        return self._sec(constitution, diff)
