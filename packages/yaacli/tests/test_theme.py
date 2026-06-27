"""Tests for the named console theme registry."""

from __future__ import annotations

from rich.theme import Theme
from yaacli.console import theme as theme_mod
from yaacli.console.theme import (
    CAPPUCCINO,
    DEFAULT_THEME_NAME,
    THEMES,
    TOKYO_NIGHT,
    build_theme,
    get_theme,
    list_themes,
    theme_exists,
)

# The exact hardcoded values from before the named-theme refactor. Locking
# them down here guarantees the default theme never regresses visually.
_HISTORICAL_DEFAULT_STYLES: dict[str, str] = {
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
    "console.dot": "bold #7dcfff",
    "console.dot.running": "#7dcfff",
    "console.dot.success": "#9ece6a",
    "console.dot.error": "#f7768e",
    "console.dot.warning": "#e0af68",
    "console.lbar": "#3b4252",
    "console.user": "bold #c099ff",
    "console.tool.name": "bold #89ddff",
    "console.tool.arg": "#aeb6c8",
    "console.tool.result": "#d8dee9",
    "console.tool.duration": "#6f778a",
    "console.tool.spinner": "#7dcfff",
    "console.tool.tag": "#6f778a italic",
    "console.thinking.gutter": "#3b4252",
    "console.thinking.text": "#6f778a italic",
    "console.diff.header": "bold",
    "console.diff.add": "green",
    "console.diff.del": "red",
    "console.diff.context": "default",
    "console.diff.meta": "dim",
    "console.todo.done": "green",
    "console.todo.in_progress": "bold yellow",
    "console.todo.pending": "dim",
    "console.error.title": "bold #f7768e",
    "console.error.body": "#f7768e",
    "console.error.frame": "#f7768e",
    "console.hitl.warn": "bold yellow",
    "console.hitl.choice_key": "bold cyan",
    "console.hitl.choice_text": "default",
    "console.steering": "bold #c099ff",
    "console.mode.act": "bold green",
    "console.mode.plan": "bold blue",
    "console.header.path": "bold #d8dee9",
    "console.header.branch": "#6f778a",
    "console.header.dirty": "#e0af68",
    "console.header.model": "bold #aeb6c8",
    "console.header.cost": "#6f778a",
    "console.footer.hint": "#6f778a",
    "console.footer.key": "bold",
    "console.footer.ready": "#9ece6a",
    "console.footer.working": "#7dcfff",
    "console.system.title": "bold #9aa5ce",
    "console.system.frame": "#3b4252",
    "console.breadcrumb": "#6f778a italic",
}


def test_default_theme_reproduces_historical_styles_exactly() -> None:
    """The tokyo-night default must be byte-identical to the pre-refactor tokens."""
    styles = theme_mod._styles_for(TOKYO_NIGHT)

    assert set(styles) == set(_HISTORICAL_DEFAULT_STYLES)
    for token, expected in _HISTORICAL_DEFAULT_STYLES.items():
        assert styles[token] == expected, f"{token}: {styles[token]!r} != {expected!r}"


def test_console_styles_module_global_matches_default_theme() -> None:
    assert theme_mod._styles_for(TOKYO_NIGHT) == theme_mod.CONSOLE_STYLES


def test_build_theme_no_arg_returns_default() -> None:
    theme = build_theme()
    assert isinstance(theme, Theme)
    # Rich parses token strings into Style objects; check the resolved color.
    assert "#7dcfff" in str(theme.styles["console.dot.running"].color)
    # Named theme produces a different resolved color than the default.
    cappuccino = build_theme("cappuccino")
    assert "#94e2d5" in str(cappuccino.styles["console.dot.running"].color)


def test_registry_exposes_default_and_cappuccino() -> None:
    assert DEFAULT_THEME_NAME == "tokyo-night"
    assert set(list_themes()) == {"tokyo-night", "cappuccino"}
    assert theme_exists("tokyo-night")
    assert theme_exists("cappuccino")
    assert not theme_exists("nope")


def test_get_theme_falls_back_to_default_for_unknown() -> None:
    assert get_theme("does-not-exist").name == DEFAULT_THEME_NAME


def test_cappuccino_uses_requested_palette() -> None:
    """The nine user-facing semantic colors map onto the cappuccino palette."""
    styles = theme_mod._styles_for(CAPPUCCINO)

    assert CAPPUCCINO.accent == "#b4befe"
    assert CAPPUCCINO.accent_assistant == "#94e2d5"
    assert CAPPUCCINO.accent_user == "#cba6f7"
    assert CAPPUCCINO.success == "#a6e3a1"
    assert CAPPUCCINO.warning == "#f9e2af"
    assert CAPPUCCINO.error == "#f38ba8"
    assert CAPPUCCINO.thinking == "#9399b2"
    assert CAPPUCCINO.muted == "#6c7086"
    assert CAPPUCCINO.subtle == "#45475a"

    # Semantic tokens consume those palette colors.
    assert styles["console.accent.user"] == "bold #cba6f7"
    assert styles["console.accent.assistant"] == "bold #94e2d5"
    assert styles["console.state.success"] == "#a6e3a1"
    assert styles["console.state.warning"] == "#f9e2af"
    assert styles["console.state.error"] == "#f38ba8"
    assert styles["console.thinking.text"] == "#9399b2 italic"
    assert styles["console.border.subtle"] == "#45475a"
    assert styles["console.text.muted"] == "#6c7086"
    # accent drives the active border / search anchor / running dot.
    assert styles["console.border.active"] == "#b4befe"
    assert styles["console.search.active"] == "black on #b4befe"
    assert styles["console.dot.running"] == "#94e2d5"


def test_each_theme_pairs_with_a_textual_theme() -> None:
    assert TOKYO_NIGHT.textual_theme == "tokyo-night"
    assert CAPPUCCINO.textual_theme == "catppuccin-mocha"
    assert all(theme.textual_theme for theme in THEMES.values())
