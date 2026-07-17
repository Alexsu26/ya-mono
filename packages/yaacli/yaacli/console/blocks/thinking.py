"""Thinking block — model's internal reasoning, rendered as a dim gutter."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Group, RenderableType

from yaacli.console.blocks.base import BaseBlock, BlockKind
from yaacli.console.design import block_body_text, block_header


@dataclass
class ThinkingBlock(BaseBlock):
    """Reasoning text. Always dim, always gutter-aligned."""

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
            block_header(
                "●",
                "thinking",
                dot_style="console.text.muted",
                label_style="console.text.muted",
            ),
            block_body_text(
                self.text,
                body_style="console.thinking.text",
            ),
        )
