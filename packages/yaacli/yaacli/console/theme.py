"""Color/style tokens for the streaming console.

Centralised so that block renderers can refer to semantic names like
``console.dot.running`` instead of raw color codes.
"""

from __future__ import annotations

from rich.theme import Theme

CONSOLE_STYLES: dict[str, str] = {
    # Transcript-first design tokens
    "console.surface.base": "#11131a",
    "console.surface.raised": "#171a23",
    "console.surface.overlay": "#1d2130",
    "console.text.primary": "#d8dee9",
    "console.text.secondary": "#aeb6c8",
    "console.text.muted": "#6f778a",
    "console.border.subtle": "#3b4252",
    "console.border.active": "#7aa2f7",
    "console.accent.user": "bold #c099ff",
    "console.accent.assistant": "bold #7dcfff",
    "console.accent.tool": "bold #89ddff",
    "console.accent.system": "#9aa5ce",
    "console.state.idle": "#8bd5a4",
    "console.state.waiting": "#e0af68",
    "console.state.running": "#7dcfff",
    "console.state.success": "#9ece6a",
    "console.state.warning": "#e0af68",
    "console.state.error": "#f7768e",
    "console.state.cancelled": "#9aa5ce",
    "console.heading.app": "bold #d8dee9",
    "console.heading.turn": "bold #d8dee9",
    "console.heading.block": "bold #c7d3f5",
    "console.meta": "#6f778a",
    "console.dim": "dim #6f778a",
    "console.code.bg": "#161821",
    "console.code.border": "#30364a",
    "console.search.match": "black on #e0af68",
    "console.search.active": "black on #7aa2f7",
    # Anchors
    "console.dot": "bold #7dcfff",
    "console.dot.running": "#7dcfff",
    "console.dot.success": "#9ece6a",
    "console.dot.error": "#f7768e",
    "console.dot.warning": "#e0af68",
    "console.lbar": "#3b4252",
    "console.user": "bold #c099ff",
    # Tool call
    "console.tool.name": "bold #89ddff",
    "console.tool.arg": "#aeb6c8",
    "console.tool.result": "#d8dee9",
    "console.tool.duration": "#6f778a",
    "console.tool.spinner": "#7dcfff",
    "console.tool.tag": "#6f778a italic",
    # Thinking
    "console.thinking.gutter": "#3b4252",
    "console.thinking.text": "#6f778a italic",
    # Diff
    "console.diff.header": "bold",
    "console.diff.add": "green",
    "console.diff.del": "red",
    "console.diff.context": "default",
    "console.diff.meta": "dim",
    # Todo
    "console.todo.done": "green",
    "console.todo.in_progress": "bold yellow",
    "console.todo.pending": "dim",
    # Error
    "console.error.title": "bold #f7768e",
    "console.error.body": "#f7768e",
    "console.error.frame": "#f7768e",
    # HITL
    "console.hitl.warn": "bold yellow",
    "console.hitl.choice_key": "bold cyan",
    "console.hitl.choice_text": "default",
    # Steering breadcrumb
    "console.steering": "bold #c099ff",
    # Mode
    "console.mode.act": "bold green",
    "console.mode.plan": "bold blue",
    # Header / footer
    "console.header.path": "bold #d8dee9",
    "console.header.branch": "#6f778a",
    "console.header.dirty": "#e0af68",
    "console.header.model": "bold #aeb6c8",
    "console.header.cost": "#6f778a",
    "console.footer.hint": "#6f778a",
    "console.footer.key": "bold",
    "console.footer.ready": "#9ece6a",
    "console.footer.working": "#7dcfff",
    # System
    "console.system.title": "bold #9aa5ce",
    "console.system.frame": "#3b4252",
    "console.breadcrumb": "#6f778a italic",
}


def build_theme() -> Theme:
    """Build the Rich Theme used by the streaming console."""
    return Theme(CONSOLE_STYLES, inherit=True)
