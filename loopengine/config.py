"""Deterministic config + safety caps. The agent has no say over these."""
from dataclasses import dataclass
from pathlib import Path

MAX_ITERATIONS = 6
MAX_WALL_SECONDS = 1200  # soft cap: checked at each iteration boundary, not mid-stage
PROTECTED = ("tests/", "constitution.md")

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
PROMPTS_DIR = SKILLS_DIR / "prompts"
RUNS_DIR = ROOT / "runs"


@dataclass
class Caps:
    max_iterations: int = MAX_ITERATIONS
    max_wall_seconds: int = MAX_WALL_SECONDS
