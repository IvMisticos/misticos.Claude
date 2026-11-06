import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import NamedTuple

from model_cap import config_folders
from plugin_paths import PLUGIN_ROOT

FRONTMATTER = re.compile(r"---\s*\n([\s\S]*?)---\s*\n?")
PLUGIN_NAME = "misticos"


class AgentFolder(NamedTuple):
    path: Path
    pattern: str
    name_prefix: str = ""


class AgentDefinition(NamedTuple):
    name: str
    model: str | None


PLUGIN_AGENTS = AgentFolder(PLUGIN_ROOT / "agents", "*.md", f"{PLUGIN_NAME}:")


def definition_text(definition_path: Path) -> str:
    try:
        return definition_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def frontmatter_fields(text: str) -> dict[str, str]:
    block = FRONTMATTER.match(text)
    if not block:
        return {}
    top_level_lines = (
        line for line in block[1].splitlines() if line and not line[0].isspace()
    )
    fields: dict[str, str] = {}
    for line in top_level_lines:
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def agent_folders(cwd: Path) -> list[AgentFolder]:
    agents = Path(".claude", "agents")
    folders = config_folders(cwd, agents, Path.home() / agents)
    return [*(AgentFolder(folder, "**/*.md") for folder in folders), PLUGIN_AGENTS]


def agent_definitions(folders: Iterable[AgentFolder]) -> Iterator[AgentDefinition]:
    for folder in folders:
        for path in sorted(folder.path.glob(folder.pattern)):
            fields = frontmatter_fields(definition_text(path))
            name = folder.name_prefix + fields.get("name", "")
            yield AgentDefinition(name, fields.get("model"))


def definition_model(subagent_type: str, folders: Iterable[AgentFolder]) -> str | None:
    models = (
        definition.model
        for definition in agent_definitions(folders)
        if definition.name == subagent_type
    )
    return next(models, None)
