from pathlib import Path
from loopengine import agents, skills
from loopengine.agents import MockAgent


def test_last_json_line_picks_final_json():
    stdout = 'progress line\n{"verdict": "pass", "gaps": []}\ntrailing noise'
    assert agents._last_json_line(stdout) == {"verdict": "pass", "gaps": []}


def test_extract_json_handles_fenced_and_prose():
    fenced = '```json\n{"verdict": "fail", "findings": []}\n```'
    assert agents._extract_json(fenced) == {"verdict": "fail", "findings": []}
    prose = 'Here is my verdict: {"verdict": "pass", "findings": []} — done.'
    assert agents._extract_json(prose) == {"verdict": "pass", "findings": []}


def test_claude_agent_parses_critic_envelope(monkeypatch, tmp_path):
    import subprocess as sp

    class _Done:
        stdout = '{"type": "result", "result": "{\\"verdict\\": \\"pass\\", \\"gaps\\": []}"}'

    monkeypatch.setattr(sp, "run", lambda *a, **k: _Done())
    agent = agents.ClaudeAgent()
    assert agent.qa_critic("s", "d", "t") == {"verdict": "pass", "gaps": []}


def test_mock_actor_runs_scripted_step(tmp_path):
    calls = []
    agent = agents.MockAgent(actor_steps=[lambda wt: calls.append(wt)])
    agent.actor("spec", "", tmp_path)
    assert calls == [tmp_path]


def test_mock_critics_default_to_pass(tmp_path):
    agent = agents.MockAgent(actor_steps=[lambda wt: None])
    assert agent.qa_critic("s", "d", "t")["verdict"] == "pass"
    assert agent.security_critic("c", "d")["verdict"] == "pass"


def test_mock_security_fn_override():
    agent = agents.MockAgent(
        actor_steps=[lambda wt: None],
        security_fn=lambda con, diff: {"verdict": "fail",
                                       "findings": [{"clause": "§1", "status": "violated",
                                                     "evidence": "float"}]})
    assert agent.security_critic("c", "d")["verdict"] == "fail"


def test_test_author_prompt_loads_with_placeholders():
    text = skills.prompt("test_author")
    assert "{spec}" in text and "{last_error}" in text
    assert "tests/acceptance" in text          # the author is told where tests go
    assert "NOT" in text                       # ... and that it must not implement


def test_mock_agent_test_author_steps_pop_in_order(tmp_path):
    calls = []
    agent = MockAgent(actor_steps=[],
                      test_author_steps=[lambda wt: calls.append(("first", wt)),
                                         lambda wt: calls.append(("second", wt))])
    agent.test_author("spec", "", tmp_path)
    agent.test_author("spec", "feedback", tmp_path)
    assert [c[0] for c in calls] == ["first", "second"]
    assert calls[0][1] == tmp_path
