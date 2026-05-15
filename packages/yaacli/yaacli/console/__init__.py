"""TUI v2 — streaming console.

Append-only block stream over rich.console.Console + rich.live.Live, with a
modal prompt_toolkit PromptSession between turns.

See packages/yaacli/spec/10-tui-v2-streaming-console.md for the design.
"""

from __future__ import annotations

from yaacli.console.app import ConsoleApp
from yaacli.console.blocks.base import Block, BlockKind
from yaacli.console.glyphs import Glyphs
from yaacli.console.stream import LiveStream
from yaacli.console.theme import build_theme

__all__ = [
    "Block",
    "BlockKind",
    "ConsoleApp",
    "Glyphs",
    "LiveStream",
    "build_theme",
]
