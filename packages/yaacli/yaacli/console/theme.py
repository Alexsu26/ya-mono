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
    # Rich Syntax highlight theme for fenced code blocks. Dark themes want a
    # dark syntax theme; light themes want a light one so code doesn't invert.
    code_syntax_theme: str = "github-dark"
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


# Graphite — the modern default. Neutral charcoal canvas, a single restrained
# indigo accent, and semantic colours reserved for status dots/labels only.
# All foreground/background pairs clear WCAG AA (>= 4.5:1) on the base surface.
GRAPHITE = ConsoleTheme(
    name="graphite",
    description="Graphite (modern default)",
    base="#0c0d10",
    raised="#14161b",
    overlay="#1b1e25",
    code_bg="#14161b",
    code_border="#23262f",
    text="#e6e7ea",
    text_secondary="#a9adb8",
    heading_block="#e6e7ea",
    muted="#6b7080",
    subtle="#23262f",
    accent="#7c9cf5",  # single brand indigo — focus + assistant
    accent_assistant="#7c9cf5",
    accent_user="#d6a35c",  # warm amber = you
    accent_tool="#6fb3c9",  # cool cyan = tool
    accent_system="#8b8f9e",
    success="#6bd08a",
    idle="#6bd08a",
    warning="#e6b455",
    error="#ec6a6a",
    thinking="#8b8f9e",
    textual_theme="textual-dark",
    overrides={
        "console.diff.add": "#6bd08a",
        "console.diff.del": "#ec6a6a",
        "console.todo.done": "#6bd08a",
        "console.todo.in_progress": "bold #e6b455",
        "console.hitl.warn": "bold #e6b455",
        "console.hitl.choice_key": "bold #7c9cf5",
        "console.mode.act": "bold #6bd08a",
        "console.mode.plan": "bold #7c9cf5",
        # Code fences: neutral surface, no harsh syntax rainbow.
        "console.code.bg": "#14161b",
        "console.code.border": "#23262f",
    },
)


# Nord Muted — a low-saturation take on the Nord palette. Cool blue-grey
# canvas (Polar Night) with a single restrained frost-blue accent. Saturation
# is deliberately pulled down from stock Nord so the transcript stays calm.
# All foreground/background pairs clear WCAG AA (>= 4.5:1) on the base surface.
NORD_MUTED = ConsoleTheme(
    name="nord-muted",
    description="Nord (low-saturation cool)",
    base="#242933",  # a touch darker than nord0 for contrast headroom
    raised="#2e3440",  # nord0
    overlay="#3b4252",  # nord1
    code_bg="#2e3440",
    code_border="#3b4252",
    text="#e5e9f0",  # nord5
    text_secondary="#c2c9d6",  # between nord4 and nord5, desaturated
    heading_block="#e5e9f0",
    muted="#7b8394",  # desaturated nord3
    subtle="#3b4252",  # nord1
    accent="#8fbcdb",  # brightened nord9/nord8 frost — the single brand blue
    accent_assistant="#8fbcdb",
    accent_user="#ebcb8b",  # nord13 warm sand = you
    accent_tool="#88c0d0",  # nord8 frost teal = tool (brighter, legible)
    accent_system="#9099ab",
    success="#a3be8c",  # nord14
    idle="#a3be8c",
    warning="#ebcb8b",  # nord13
    error="#bf616a",  # nord11
    thinking="#9099ab",
    textual_theme="nord",
    code_syntax_theme="nord",
    overrides={
        "console.diff.add": "#a3be8c",
        "console.diff.del": "#bf616a",
        "console.todo.done": "#a3be8c",
        "console.todo.in_progress": "bold #ebcb8b",
        "console.hitl.warn": "bold #ebcb8b",
        "console.hitl.choice_key": "bold #8fbcdb",
        "console.mode.act": "bold #a3be8c",
        "console.mode.plan": "bold #8fbcdb",
    },
)


# Daybreak — a light theme in the GitHub Light family. Near-white paper canvas,
# calm ink text, and a single blue accent. Semantic colours are chosen to keep
# >= 4.5:1 contrast against the light surface (darker than their dark-theme
# counterparts). Syntax highlighting switches to a light code theme so fenced
# blocks don't invert into a dark rectangle on the light page.
DAYBREAK = ConsoleTheme(
    name="daybreak",
    description="GitHub Light (paper)",
    base="#ffffff",
    raised="#f6f8fa",
    overlay="#eaeef2",
    code_bg="#f6f8fa",
    code_border="#d0d7de",
    text="#1f2328",
    text_secondary="#57606a",
    heading_block="#1f2328",
    muted="#6e7781",
    subtle="#d0d7de",
    accent="#0969da",  # github blue
    accent_assistant="#0969da",
    accent_user="#9a6700",  # dark amber = you (AA on white)
    accent_tool="#1b7c83",  # teal = tool (AA on white)
    accent_system="#6e7781",
    success="#1a7f37",  # github green (dark enough for white bg)
    idle="#1a7f37",
    warning="#9a6700",  # github attention (dark amber)
    error="#cf222e",  # github danger red
    thinking="#6e7781",
    textual_theme="textual-light",
    code_syntax_theme="github-light",
    overrides={
        "console.diff.add": "#1a7f37",
        "console.diff.del": "#cf222e",
        "console.todo.done": "#1a7f37",
        "console.todo.in_progress": "bold #9a6700",
        "console.hitl.warn": "bold #9a6700",
        "console.hitl.choice_key": "bold #0969da",
        "console.mode.act": "bold #1a7f37",
        "console.mode.plan": "bold #0969da",
        "console.code.bg": "#f6f8fa",
        "console.code.border": "#d0d7de",
    },
)


THEMES: dict[str, ConsoleTheme] = {
    theme.name: theme for theme in (GRAPHITE, TOKYO_NIGHT, CAPPUCCINO, NORD_MUTED, DAYBREAK)
}
DEFAULT_THEME_NAME = "graphite"


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
        "console.accent": theme.accent,
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
        "console.tool.name": f"bold {theme.text}",
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
        "console.header.branch": theme.text_secondary,
        "console.header.dirty": theme.warning,
        "console.header.model": theme.text_secondary,
        "console.header.cost": theme.muted,
        "console.header.divider": theme.subtle,
        "console.header.icon": theme.muted,
        "console.header.ctx": theme.accent,
        "console.footer.hint": theme.muted,
        "console.footer.key": "bold",
        "console.footer.ready": theme.success,
        "console.footer.working": theme.accent_assistant,
        # System
        "console.system.title": f"bold {theme.accent_system}",
        "console.system.frame": theme.subtle,
        "console.breadcrumb": f"{theme.muted} italic",
        # Rich Markdown surfaces (inherit=True lets these override defaults).
        # Inline code / paths stay a calm secondary tone instead of a loud
        # accent so a paragraph full of `code` doesn't turn into rainbow noise.
        "markdown.code": theme.text_secondary,
        "markdown.code_block": theme.text_secondary,
        "markdown.link": theme.accent,
        "markdown.link_url": theme.muted,
        "markdown.item.bullet": f"bold {theme.accent}",
        "markdown.h1": f"bold {theme.text}",
        "markdown.h2": f"bold {theme.text}",
        "markdown.h3": f"bold {theme.heading_block}",
        "markdown.h4": f"bold {theme.heading_block}",
    }
    # Per-theme overrides win last.
    styles.update(theme.overrides)
    return styles


# Backward-compatible module-level styles for the default theme.
CONSOLE_STYLES: dict[str, str] = _styles_for(TOKYO_NIGHT)

# Tracks the Rich Syntax code theme for the most recently built theme so that
# block renderers (which only receive a width) can highlight fenced code with a
# palette that matches the active console theme. Updated by ``build_theme``.
_active_code_syntax_theme: str = get_theme(DEFAULT_THEME_NAME).code_syntax_theme


def active_code_syntax_theme() -> str:
    """Rich Syntax code theme paired with the most recently built console theme."""
    return _active_code_syntax_theme


_active_theme_name: str = DEFAULT_THEME_NAME


def active_theme_name() -> str:
    """Name of the most recently built console theme."""
    return _active_theme_name


def set_active_theme_name(name: str) -> None:
    """Record the active console theme so chrome renderers resolve its palette."""
    global _active_theme_name
    _active_theme_name = name if theme_exists(name) else DEFAULT_THEME_NAME


def build_theme(name: str = DEFAULT_THEME_NAME) -> Theme:
    """Build the Rich Theme used by the streaming console.

    Args:
        name: Registered theme name (defaults to the default theme).
    """
    global _active_code_syntax_theme, _active_theme_name
    theme = get_theme(name)
    _active_code_syntax_theme = theme.code_syntax_theme
    _active_theme_name = theme.name
    return Theme(_styles_for(theme), inherit=True)


def build_textual_theme(name: str = DEFAULT_THEME_NAME) -> object:
    """Build the Textual ``Theme`` that colors widget chrome for a console theme.

    Rather than pairing each console theme with a pre-existing Textual built-in
    (which never matches the palette exactly and leaves hardcoded CSS colors
    stranded), we synthesise a Textual theme straight from the console palette.
    The app registers this under ``yaacli-<name>``; every chrome surface
    (header, footer, composer, scrollbars, focus borders) is styled through the
    built-in Textual design tokens (``$background``/``$surface``/``$panel``/
    ``$foreground``/``$primary``) that this theme populates from the palette, so
    switching themes recolors the whole UI with no black remnants.
    """
    from textual.theme import Theme as TextualTheme

    theme = get_theme(name)
    return TextualTheme(
        name=f"yaacli-{theme.name}",
        primary=theme.accent,
        secondary=theme.accent_assistant,
        accent=theme.accent,
        warning=theme.warning,
        error=theme.error,
        success=theme.success,
        foreground=theme.text,
        background=theme.base,
        surface=theme.raised,
        panel=theme.overlay,
        dark=name != "daybreak",
    )
