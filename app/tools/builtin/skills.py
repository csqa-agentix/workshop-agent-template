"""Built-in tool: let the agent read a skill file on demand (only used when SKILLS_MODE=on_demand)."""
from __future__ import annotations

from app.config import load_settings
from app.prompts.loader import list_skills
from app.tools.registry import tool


@tool
def load_skill(name: str) -> str:
    """Read the full text of one skill from the prompt library. Only use names listed under SKILLS in your instructions."""
    skills = {n: body for n, _, body in list_skills(load_settings().prompts_dir)}
    if name not in skills:
        raise ValueError(f"Unknown skill '{name}'. Available: {sorted(skills)}")
    return skills[name]
