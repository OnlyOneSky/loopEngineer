"""Skills — codified project knowledge, read-only to the actor."""
from .config import PROMPTS_DIR, SKILLS_DIR


def constitution() -> str:
    return (SKILLS_DIR / "constitution.md").read_text(encoding="utf-8")


def prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")
