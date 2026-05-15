"""Thinking block — model's internal reasoning, rendered as a dim gutter."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Group, RenderableType

from yaacli.console.blocks.base import BaseBlock, BlockKind
from yaacli.console.design import rail_text, turn_header


@dataclass
class ThinkingBlock(BaseBlock):
    """Reasoning text. Always dim, always gutter-prefixed."""

    chunks: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.kind = BlockKind.THINKING
        super().__post_init__()

    def append(self, delta: str) -> None:
        self.chunks.append(delta)

    @property
    def text(self) -> str:
        return "".join(self.chunks)

    def render(self, width: int) -> RenderableType:
        return Group(
            turn_header(
                "◇",
                "thinking",
                glyph_style="console.text.muted",
                label_style="console.text.muted",
            ),
            rail_text(
                self.text,
                rail_style="console.thinking.gutter",
                body_style="console.thinking.text",
            ),
        )
