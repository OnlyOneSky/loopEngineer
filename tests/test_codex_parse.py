from pathlib import Path
from loopengine import agents


def test_last_json_line_parses_real_codex_sample():
    sample = (Path(__file__).parent / "fixtures" / "codex_events.jsonl").read_text()
    verdict = agents._last_json_line(sample)
    # The fixture's final JSON line is the verdict object the orchestrator consumes.
    assert verdict.get("verdict") == "pass"
    assert verdict["findings"][0]["clause"] == "§1"
