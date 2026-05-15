"""User prompt block: ``▌ <utterance>``."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType

from yaacli.console.blocks.base import BaseBlock, BlockKind
from yaacli.console.design import rail_text, turn_header
from yaacli.console.glyphs import GLYPHS


@dataclass
class UserPromptBlock(BaseBlock):
    """Echo of the user utterance that started the current turn."""

    text: str = ""

    def __post_init__(self) -> None:
        self.kind = BlockKind.USER_PROMPT
        super().__post_init__()
        self.state.is_terminal = True

    def render(self, width: int) -> RenderableType:
        return Group(
            turn_header(
                GLYPHS.USER,
                "you",
                glyph_style="console.accent.user",
                label_style="console.accent.user",
            ),
            rail_text(self.text, rail="  ", body_style="console.text.primary"),
        )
