"""System / slash-command output block.

Used by /cost, /perf, /help, /session, etc. so that command output uses the
same anchor + panel vocabulary as agent output.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from yaacli.console.blocks.base import BaseBlock, BlockKind
from yaacli.console.design import rail_renderable, rail_text, turn_header


@dataclass
class SystemBlock(BaseBlock):
    """A system-output block. ``body`` may be any rich renderable or a string."""

    title: str = ""
    body: RenderableType | str = ""
    boxed: bool = False

    def __post_init__(self) -> None:
        self.kind = BlockKind.SYSTEM
        super().__post_init__()
        self.state.is_terminal = True

    def render(self, width: int) -> RenderableType:
        header = turn_header(
            "◆",
            "system",
            meta=self.title,
            glyph_style="console.accent.system",
            label_style="console.system.title",
        )

        body: RenderableType
        if isinstance(self.body, str):
            body = Text(self.body)
        else:
            body = self.body

        if not self.boxed:
            if isinstance(self.body, str):
                return Group(header, rail_text(self.body, body_style="console.text.secondary"))
            return Group(header, rail_renderable(body))

        panel_width = max(40, min(width - 2, 120))
        panel = Panel(
            body,
            border_style="console.system.frame",
            padding=(0, 1),
            width=panel_width,
        )
        return Group(header, panel)


@dataclass
class BreadcrumbBlock(BaseBlock):
    """A one-line marker (mode switch, steering injected, etc.)."""

    text: str = ""

    def __post_init__(self) -> None:
        self.kind = BlockKind.BREADCRUMB
        super().__post_init__()
        self.state.is_terminal = True

    def render(self, width: int) -> RenderableType:
        return Text(self.text, style="console.breadcrumb")
