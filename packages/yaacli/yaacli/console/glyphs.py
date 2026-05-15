"""Single source of truth for visual glyphs in the streaming console.

See spec/10-tui-v2-streaming-console.md §"Visual Language".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Glyphs:
    """Glyph constants used across all block renderers."""

    DOT: str = "⏺"
    L_BAR: str = "⎿"
    USER: str = "▌"
    GUTTER: str = "│"
    BULLET_TASK: str = "⏵"
    DIAMOND: str = "◆"
    CHECK: str = "✓"
    CROSS: str = "✗"
    WARNING: str = "⚠"
    PROGRESS: str = "▶"
    EMPTY: str = "◯"


GLYPHS = Glyphs()

SPINNER_FRAMES = ["⡀", "⡄", "⡆", "⡇", "⠏", "⠋", "⠹", "⠸"]
