"""Error block — never collapses; renders inside a red panel."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.text import Text

from yaacli.console.blocks.base import BaseBlock, BlockKind
from yaacli.console.design import rail_text, turn_header


@dataclass
class ErrorBlock(BaseBlock):
    """Failure surface for tools, exceptions, or generic errors."""

    title: str = "Error"
    body: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        self.kind = BlockKind.ERROR
        super().__post_init__()
        self.state.is_terminal = True
        self.state.error = True

    def render(self, width: int) -> RenderableType:
        header = turn_header(
            "✖",
            "error",
            meta=self.title,
            glyph_style="console.state.error",
            label_style="console.error.title",
        )
        body_parts: list[RenderableType] = []
        if self.body:
            body_parts.append(rail_text(self.body, body_style="console.error.body"))
        if self.detail:
            detail = Text()
            detail.append("  │ detail", style="console.meta")
            body_parts.append(detail)
            body_parts.append(rail_text(self.detail, body_style="console.text.muted"))
        return Group(header, *body_parts)
