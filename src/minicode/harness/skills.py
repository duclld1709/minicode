"""Skills with progressive disclosure.

A skill is a folder `.minicode/skills/<name>/SKILL.md`:

    ---
    name: write-pytest-tests
    description: How to write focused pytest tests. Use when adding or fixing tests.
    ---
    (full instructions, examples, checklists...)

Only `name` + `description` go into the system prompt (a few dozen tokens per
skill). The body is loaded on demand through the `load_skill` tool when the model
decides it is relevant. That way a project can have many detailed skills without
paying for all of them on every request.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from minicode.tools.base import Tool, ToolError

SKILLS_DIR = Path(".minicode") / "skills"
SKILL_FILE = "SKILL.md"


@dataclass
class Skill:
    name: str
    description: str
    path: Path  # the SKILL.md file


def parse_skill_file(path: Path) -> tuple[dict[str, object], str]:
    """Split a SKILL.md into (frontmatter dict, body). Frontmatter is optional YAML between ---."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}, text.strip()
    _, _, rest = text.partition("---")
    header, separator, body = rest.partition("\n---")
    if not separator:
        return {}, text.strip()
    data = yaml.safe_load(header) or {}
    if not isinstance(data, dict):
        return {}, body.strip()
    return data, body.strip()


def discover_skills(workspace: Path) -> list[Skill]:
    """Find skills; a SKILL.md without both `name` and `description` is skipped."""
    # Absolute paths, so "other files" listed by load_skill work with read_file from anywhere.
    root = workspace.resolve() / SKILLS_DIR
    if not root.is_dir():
        return []
    skills = []
    for path in sorted(root.glob(f"*/{SKILL_FILE}")):
        try:
            meta, _ = parse_skill_file(path)
        except yaml.YAMLError:
            continue  # a broken skill must not break the agent
        name, description = meta.get("name"), meta.get("description")
        if isinstance(name, str) and isinstance(description, str):
            skills.append(Skill(name=name, description=description.strip(), path=path))
    return skills


class LoadSkillArgs(BaseModel):
    name: str = Field(description="Name of the skill to load, exactly as listed in 'Skills'.")


LOAD_SKILL_DOC = (
    "Load the full instructions of a skill listed in the system prompt. Call it as soon as a "
    "skill's description matches the task, before doing the work."
)


def make_skill_tool(skills: list[Skill]) -> Tool:
    """The `load_skill` tool: returns a skill's body plus the other files in its folder."""
    by_name = {skill.name: skill for skill in skills}

    def load_skill(args: LoadSkillArgs) -> str:
        skill = by_name.get(args.name)
        if skill is None:
            raise ToolError(f"Unknown skill '{args.name}'. Available: {', '.join(by_name)}.")
        _, body = parse_skill_file(skill.path)
        extras = sorted(p.name for p in skill.path.parent.iterdir() if p.name != SKILL_FILE)
        if extras:
            folder = skill.path.parent.as_posix()
            body += f"\n\nOther files in this skill (read with read_file): {folder}/: " + ", ".join(
                extras
            )
        return f"# Skill: {skill.name}\n\n{body}"

    return Tool("load_skill", LOAD_SKILL_DOC, LoadSkillArgs, load_skill, "read")
