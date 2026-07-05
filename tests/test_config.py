from loopengine import config


def test_caps_defaults_match_module_constants():
    caps = config.Caps()
    assert caps.max_iterations == config.MAX_ITERATIONS == 6
    assert caps.max_wall_seconds == config.MAX_WALL_SECONDS == 1200


def test_protected_paths():
    assert config.PROTECTED == ("tests/", "constitution.md", "AGENTS.md", "CLAUDE.md")


def test_paths_anchor_to_project_root():
    assert config.SKILLS_DIR == config.ROOT / "skills"
    assert config.PROMPTS_DIR == config.SKILLS_DIR / "prompts"
    assert config.RUNS_DIR == config.ROOT / "runs"
