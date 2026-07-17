"""User prompt block: ``▌ <utterance>``."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType

from yaacli.console.blocks.base import BaseBlock, BlockKind
from yaacli.console.design import block_body_text, block_header


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
            block_header(
                "●",
                "you",
                dot_style="console.accent.user",
                label_style="console.accent.user",
            ),
            block_body_text(self.text, body_style="console.text.primary"),
        )
