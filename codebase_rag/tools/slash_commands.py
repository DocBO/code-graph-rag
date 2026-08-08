from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    usage: str


_COMMANDS = {
    "/help": SlashCommand(
        name="/help",
        description="List available slash commands.",
        usage="/help",
    ),
    "/semantic-seed-strategy": SlashCommand(
        name="/semantic-seed-strategy",
        description="Run semantic search, expand graph neighbors, then answer.",
        usage="/semantic-seed-strategy <your question>",
    ),
}


def parse_slash_command(text: str) -> tuple[str | None, str]:
    stripped = text.lstrip()
    if not stripped.startswith("/"):
        return None, text
    parts = stripped.split(maxsplit=1)
    command = parts[0]
    remainder = parts[1] if len(parts) == 2 else ""
    if command in _COMMANDS:
        return command, remainder
    return None, text


def get_help_text() -> str:
    lines = ["Available commands:"]
    for command in _COMMANDS.values():
        lines.append(f"- {command.name}: {command.description}")
        lines.append(f"  Usage: {command.usage}")
    return "\n".join(lines)


def has_command(command: str) -> bool:
    return command in _COMMANDS


def get_command_list() -> list[str]:
    """Return list of all command names for autocomplete."""
    return list(_COMMANDS.keys())
