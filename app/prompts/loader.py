"""MODULE 5 · PROMPT LOADER – builds the system prompt from the markdown files in the prompt library.

  system.md   generic rules of autonomy           (framework – usually leave alone)
  agent.md    YOUR agent: role, workflow, rules   (edit this first!)
  skills/*.md reusable know-how, one file each    (add as many as you like)
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


def read_skill(path: Path) -> tuple[str, str, str]:
    """Return (name, description, body). A skill file starts with '---\\nname: …\\ndescription: …\\n---'."""
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(text)
    meta, body = ({}, text)
    if match:
        meta = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
        body = match.group(2)
    return meta.get("name", path.stem).strip(), meta.get("description", "").strip(), body.strip()


def list_skills(prompts_dir: Path) -> list[tuple[str, str, str]]:
    return [read_skill(p) for p in sorted((prompts_dir / "skills").glob("*.md"))]


def build_system_prompt(prompts_dir: Path, *, max_turns: int, skills_mode: str = "inline", today: date | None = None) -> str:
    system = (prompts_dir / "system.md").read_text(encoding="utf-8") if (prompts_dir / "system.md").exists() \
        else (Path(__file__).parent / "system.md").read_text(encoding="utf-8")
    agent = (prompts_dir / "agent.md").read_text(encoding="utf-8")
    skills = list_skills(prompts_dir)
    if skills_mode == "on_demand":
        skills_block = "=== SKILLS (call the load_skill tool to read one before you need it) ===\n" + \
            "\n".join(f"- {n}: {d}" for n, d, _ in skills)
    else:
        skills_block = "\n\n".join(f"=== SKILL: {n} ===\n{b}" for n, _, b in skills)
    system = system.replace("{{max_turns}}", str(max_turns)).replace("{{today}}", str(today or date.today()))
    return f"{system.strip()}\n\n=== YOUR ROLE AND WORKFLOW ===\n{agent.strip()}\n\n{skills_block}".strip()
