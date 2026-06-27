"""Color/style tokens for the streaming console.

Centralised so that block renderers can refer to semantic names like
``console.dot.running`` instead of raw color codes.

The console supports multiple named themes (see ``THEMES``). Each theme is a
small semantic palette that is expanded into the full token set by
``_styles_for``. The default theme (``tokyo-night``) reproduces the historical
hard-coded colors exactly; ``cappuccino`` is a Catppuccin Mocha palette.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.theme import Theme


@dataclass(frozen=True)
class ConsoleTheme:
    """A semantic color palette that drives the full style token set.

    Fields map 1:1 to the roles used across block renderers. ``textual_theme``
    is the optional Textual built-in theme that pairs with this console theme
    (controls widget chrome — status bar, input, borders). ``overrides`` lets a
    theme replace any individual token's full style string after the palette is
    expanded, so named-color tokens (diff/todo/mode) can be themed without
    disturbing the default theme's exact colors.
    """

    name: str
    description: str
    # Neutral surfaces and text
    base: str
    raised: str
    overlay: str
    code_bg: str
    code_border: str
    text: str
    text_secondary: str
    heading_block: str
    muted: str
    subtle: str
    # Accents and state colors
    accent: str
    accent_assistant: str
    accent_user: str
    accent_tool: str
    accent_system: str
    success: str
    idle: str
    warning: str
    error: str
    thinking: str
    # Optional Textual built-in theme to pair with for widget chrome.
    textual_theme: str | None = None
    # Per-token style overrides applied after palette expansion.
    overrides: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Built-in themes
# ---------------------------------------------------------------------------

TOKYO_NIGHT = ConsoleTheme(
    name="tokyo-night",
    description="Tokyo Night (default)",
    base="#11131a",
    raised="#171a23",
    overlay="#1d2130",
    code_bg="#161821",
    code_border="#30364a",
    text="#d8dee9",
    text_secondary="#aeb6c8",
    heading_block="#c7d3f5",
    muted="#6f778a",
    subtle="#3b4252",
    accent="#7aa2f7",
    accent_assistant="#7dcfff",
    accent_user="#c099ff",
    accent_tool="#89ddff",
    accent_system="#9aa5ce",
    success="#9ece6a",
    idle="#8bd5a4",
    warning="#e0af68",
    error="#f7768e",
    thinking="#6f778a",
    textual_theme="tokyo-night",
)

# Cappuccino — Catppuccin Mocha. The nine user-facing semantic colors below
# are the ones a user picks when choosing a palette; the neutrals round it out.
CAPPUCCINO = ConsoleTheme(
    name="cappuccino",
    description="Catppuccin Mocha",
    base="#1e1e2e",
    raised="#181825",
    overlay="#11111b",
    code_bg="#181825",
    code_border="#313244",
    text="#cdd6f4",
    text_secondary="#bac2de",
    heading_block="#cdd6f4",
    muted="#6c7086",  # surface2
    subtle="#45475a",  # surface1
    accent="#b4befe",  # lavender
    accent_assistant="#94e2d5",  # teal
    accent_user="#cba6f7",  # mauve
    accent_tool="#94e2d5",  # teal (pairs with assistant, like tokyo-night)
    accent_system="#9399b2",  # subtext0
    success="#a6e3a1",  # green
    idle="#a6e3a1",  # green
    warning="#f9e2af",  # yellow
    error="#f38ba8",  # red
    thinking="#9399b2",  # subtext0
    textual_theme="catppuccin-mocha",
    overrides={
        # Theme the named-color tokens so diffs/todos/mode follow the palette.
        "console.diff.add": "#a6e3a1",
        "console.diff.del": "#f38ba8",
        "console.todo.done": "#a6e3a1",
        "console.todo.in_progress": "bold #f9e2af",
        "console.hitl.warn": "bold #f9e2af",
        "console.hitl.choice_key": "bold #b4befe",
        "console.mode.act": "bold #a6e3a1",
        "console.mode.plan": "bold #b4befe",
    },
)


THEMES: dict[str, ConsoleTheme] = {theme.name: theme for theme in (TOKYO_NIGHT, CAPPUCCINO)}
DEFAULT_THEME_NAME = "tokyo-night"


def get_theme(name: str) -> ConsoleTheme:
    """Return the named theme, falling back to the default if unknown."""
    return THEMES.get(name, THEMES[DEFAULT_THEME_NAME])


def theme_exists(name: str) -> bool:
    """True if ``name`` is a registered theme."""
    return name in THEMES


def list_themes() -> list[str]:
    """Registered theme names in definition order."""
    return list(THEMES)


def _styles_for(theme: ConsoleTheme) -> dict[str, str]:
    """Expand a semantic palette into the full token set."""
    styles: dict[str, str] = {
        # Transcript-first design tokens
        "console.surface.base": theme.base,
        "console.surface.raised": theme.raised,
        "console.surface.overlay": theme.overlay,
        "console.text.primary": theme.text,
        "console.text.secondary": theme.text_secondary,
        "console.text.muted": theme.muted,
        "console.border.subtle": theme.subtle,
        "console.border.active": theme.accent,
        "console.accent.user": f"bold {theme.accent_user}",
        "console.accent.assistant": f"bold {theme.accent_assistant}",
        "console.accent.tool": f"bold {theme.accent_tool}",
        "console.accent.system": theme.accent_system,
        "console.state.idle": theme.idle,
        "console.state.waiting": theme.warning,
        "console.state.running": theme.accent_assistant,
        "console.state.success": theme.success,
        "console.state.warning": theme.warning,
        "console.state.error": theme.error,
        "console.state.cancelled": theme.accent_system,
        "console.heading.app": f"bold {theme.text}",
        "console.heading.turn": f"bold {theme.text}",
        "console.heading.block": f"bold {theme.heading_block}",
        "console.meta": theme.muted,
        "console.dim": f"dim {theme.muted}",
        "console.code.bg": theme.code_bg,
        "console.code.border": theme.code_border,
        "console.search.match": f"black on {theme.warning}",
        "console.search.active": f"black on {theme.accent}",
        # Anchors
        "console.dot": f"bold {theme.accent_assistant}",
        "console.dot.running": theme.accent_assistant,
        "console.dot.success": theme.success,
        "console.dot.error": theme.error,
        "console.dot.warning": theme.warning,
        "console.lbar": theme.subtle,
        "console.user": f"bold {theme.accent_user}",
        # Tool call
        "console.tool.name": f"bold {theme.accent_tool}",
        "console.tool.arg": theme.text_secondary,
        "console.tool.result": theme.text,
        "console.tool.duration": theme.muted,
        "console.tool.spinner": theme.accent_assistant,
        "console.tool.tag": f"{theme.muted} italic",
        # Thinking
        "console.thinking.gutter": theme.subtle,
        "console.thinking.text": f"{theme.thinking} italic",
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
        "console.error.title": f"bold {theme.error}",
        "console.error.body": theme.error,
        "console.error.frame": theme.error,
        # HITL
        "console.hitl.warn": "bold yellow",
        "console.hitl.choice_key": "bold cyan",
        "console.hitl.choice_text": "default",
        # Steering breadcrumb
        "console.steering": f"bold {theme.accent_user}",
        # Mode
        "console.mode.act": "bold green",
        "console.mode.plan": "bold blue",
        # Header / footer
        "console.header.path": f"bold {theme.text}",
        "console.header.branch": theme.muted,
        "console.header.dirty": theme.warning,
        "console.header.model": f"bold {theme.text_secondary}",
        "console.header.cost": theme.muted,
        "console.footer.hint": theme.muted,
        "console.footer.key": "bold",
        "console.footer.ready": theme.success,
        "console.footer.working": theme.accent_assistant,
        # System
        "console.system.title": f"bold {theme.accent_system}",
        "console.system.frame": theme.subtle,
        "console.breadcrumb": f"{theme.muted} italic",
    }
    # Per-theme overrides win last.
    styles.update(theme.overrides)
    return styles


# Backward-compatible module-level styles for the default theme.
CONSOLE_STYLES: dict[str, str] = _styles_for(TOKYO_NIGHT)


def build_theme(name: str = DEFAULT_THEME_NAME) -> Theme:
    """Build the Rich Theme used by the streaming console.

    Args:
        name: Registered theme name (defaults to the default theme).
    """
    return Theme(_styles_for(get_theme(name)), inherit=True)
