"""Slash command palette.

A self-contained Float over the prompt line. Built on prompt_toolkit because
that's where we're already getting input — but the rendering is fully custom
so we can group, show parameter placeholders, and add shortcut hints.

The palette degrades gracefully: if it can't be shown (terminal too narrow,
no TTY), it's silently bypassed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText, StyleAndTextTuples

GroupName = Literal["MODE", "SESSION", "WORKSPACE", "INSPECT", "OTHER"]


@dataclass(frozen=True)
class SlashParam:
    name: str
    required: bool = True


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    group: GroupName = "OTHER"
    params: tuple[SlashParam, ...] = ()
    shortcut: str | None = None


GROUP_ORDER: tuple[GroupName, ...] = ("MODE", "SESSION", "WORKSPACE", "INSPECT", "OTHER")


# Default registry — these mirror the v1 builtin slash commands.
DEFAULT_COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("act", "Switch to ACT mode", "MODE"),
    SlashCommand("plan", "Switch to PLAN mode", "MODE"),
    SlashCommand("clear", "Clear conversation history", "SESSION"),
    SlashCommand("session", "List or restore saved sessions", "SESSION", (SlashParam("id", required=False),)),
    SlashCommand("sessions", "List saved sessions", "SESSION"),
    SlashCommand("resume", "Resume a saved session", "SESSION", (SlashParam("id", required=False),)),
    SlashCommand("rename", "Rename current session", "SESSION", (SlashParam("name", required=True),)),
    SlashCommand("export", "Export current session as Markdown", "SESSION", (SlashParam("path", required=False),)),
    SlashCommand("dump", "Dump current session history", "SESSION", (SlashParam("path", required=False),)),
    SlashCommand("load", "Load conversation from a folder", "SESSION", (SlashParam("folder", required=True),)),
    SlashCommand("init", "Initialize AGENTS.md", "WORKSPACE"),
    SlashCommand("commit", "Review and commit changes", "WORKSPACE"),
    SlashCommand("review", "Comprehensive code review", "WORKSPACE"),
    SlashCommand("cost", "Show token usage and estimated cost", "INSPECT"),
    SlashCommand("search", "Search output history", "INSPECT", (SlashParam("query", required=True),), "ctrl+f"),
    SlashCommand("jump", "Jump to user/assistant/tool/error marker", "INSPECT", (SlashParam("marker", required=True),)),
    SlashCommand("perf", "Show performance metrics", "INSPECT"),
    SlashCommand("model", "List or switch model profiles", "INSPECT", (SlashParam("name", required=False),)),
    SlashCommand("theme", "Show or switch color theme", "INSPECT", (SlashParam("name", required=False),)),
    SlashCommand("skills", "List available skills", "INSPECT", (SlashParam("query", required=False),)),
    SlashCommand("skill", "Show skill details", "INSPECT", (SlashParam("name", required=True),)),
    SlashCommand("mcp", "List configured MCP servers", "INSPECT", (SlashParam("query", required=False),)),
    SlashCommand("subagents", "List configured subagents", "INSPECT", (SlashParam("query", required=False),)),
    SlashCommand("subagent", "Show subagent details", "INSPECT", (SlashParam("name", required=True),)),
    SlashCommand("tasks", "Show active tasks and processes", "INSPECT"),
    SlashCommand(
        "delegate",
        "Run a subagent and wait for result",
        "OTHER",
        (SlashParam("subagent", required=True), SlashParam("prompt", required=True)),
    ),
    SlashCommand(
        "spawn",
        "Start a background subagent",
        "OTHER",
        (SlashParam("subagent", required=True), SlashParam("prompt", required=True)),
    ),
    SlashCommand(
        "goal",
        "Run autonomously until the task is verified",
        "OTHER",
        (SlashParam("task", required=True),),
    ),
    SlashCommand("paste-image", "Attach an image from the clipboard", "OTHER"),
    SlashCommand("help", "Show available commands", "OTHER"),
    SlashCommand("exit", "Exit yaacli", "OTHER"),
)


def _format_param(param: SlashParam) -> str:
    return f"<{param.name}>" if param.required else f"[{param.name}]"


@dataclass
class SlashCompleter(Completer):
    """Custom completer that emits grouped, formatted slash entries."""

    get_commands: Callable[[], Iterable[SlashCommand]] = field(default=lambda: DEFAULT_COMMANDS)

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        if "\n" in text or any(ch.isspace() for ch in text):
            return
        prefix = text[1:].lower()
        replace_len = len(prefix) + 1

        commands = list(self.get_commands())
        # Sort: group order first, then alphabetical within group
        group_idx = {g: i for i, g in enumerate(GROUP_ORDER)}
        commands.sort(key=lambda c: (group_idx.get(c.group, 99), c.name))

        last_group: str | None = None
        for cmd in commands:
            if not cmd.name.startswith(prefix):
                continue

            display_tuples: StyleAndTextTuples = []
            if cmd.group != last_group:
                display_tuples.append(("class:slash.group", f"{cmd.group:<10}"))
                last_group = cmd.group
            else:
                display_tuples.append(("", " " * 10))

            display_tuples.append(("class:slash.name", f"/{cmd.name:<14}"))
            display_tuples.append(("class:slash.desc", cmd.description))

            for param in cmd.params:
                style = "class:slash.required" if param.required else "class:slash.optional"
                display_tuples.append(("", "  "))
                display_tuples.append((style, _format_param(param)))

            if cmd.shortcut:
                display_tuples.append(("", "  "))
                display_tuples.append(("class:slash.shortcut", cmd.shortcut))

            display = FormattedText(display_tuples)
            yield Completion(
                f"/{cmd.name}",
                start_position=-replace_len,
                display=display,
                display_meta="",
            )


SLASH_PALETTE_STYLES: dict[str, str] = {
    "completion-menu": "bg:#1a1a2e fg:#d7d9f0",
    "completion-menu.completion": "bg:#1a1a2e fg:#d7d9f0",
    "completion-menu.completion.current": "bg:#3b4261 fg:#ffffff bold",
    "completion-menu.meta.completion": "bg:#1a1a2e fg:#737aa2",
    "completion-menu.meta.completion.current": "bg:#3b4261 fg:#ffffff",
    "slash.group": "fg:#7aa2f7 bold",
    "slash.name": "fg:#9ece6a bold",
    "slash.desc": "fg:#c0caf5",
    "slash.required": "fg:#7dcfff",
    "slash.optional": "fg:#737aa2 italic",
    "slash.shortcut": "fg:#bb9af7 italic",
}
