"""Model text block: streaming markdown from the assistant."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.text import Text

from yaacli.console.blocks.base import BaseBlock, BlockKind
from yaacli.console.design import turn_header
from yaacli.console.theme import ThemeName, code_theme_for

_MAX_MARKDOWN_RENDER_CHARS = 80_000
ASSISTANT_MARKDOWN_CODE_THEME = "github-dark"


@dataclass
class ModelTextBlock(BaseBlock):
    """Markdown response from the model. Mutable while streaming."""

    chunks: list[str] = field(default_factory=list)
    theme_name: ThemeName = "dark"
    show_header: bool = True

    def __post_init__(self) -> None:
        self.kind = BlockKind.MODEL_TEXT
        super().__post_init__()

    @property
    def text(self) -> str:
        return "".join(self.chunks)

    def append(self, delta: str) -> None:
        self.chunks.append(delta)

    def render(self, width: int) -> RenderableType:
        if not self.chunks:
            return Text("")
        text = self.text
        if len(text) > _MAX_MARKDOWN_RENDER_CHARS:
            hidden = len(text) - _MAX_MARKDOWN_RENDER_CHARS
            text = (
                text[:_MAX_MARKDOWN_RENDER_CHARS]
                + f"\n\n[output clipped: {hidden} chars hidden; use /export to show more]"
            )
        body = Padding(
            Markdown(
                text,
                code_theme=code_theme_for(self.theme_name),
                style="console.text.primary",
            ),
            (0, 0, 0, 4),
        )
        if not self.show_header:
            return body
        return Group(
            turn_header(
                "●",
                "assistant",
                glyph_style="console.accent.assistant",
                label_style="console.heading.turn",
            ),
            body,
        )
