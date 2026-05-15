"""HITL approval block — inline keystroke prompt for risky tool runs."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Group, RenderableType
from rich.text import Text

from yaacli.console.blocks.base import BaseBlock, BlockKind
from yaacli.console.glyphs import GLYPHS


@dataclass
class HitlChoice:
    key: str
    label: str


_DEFAULT_CHOICES = [
    HitlChoice("y", "approve once"),
    HitlChoice("a", "approve all this session"),
    HitlChoice("n", "reject (model will see denial)"),
    HitlChoice("e", "edit before running"),
]


@dataclass
class HitlBlock(BaseBlock):
    """Render the approval prompt above the live key reader."""

    tool_name: str = ""
    summary: str = ""
    tag: str = "needs approval"
    choices: list[HitlChoice] = field(default_factory=lambda: list(_DEFAULT_CHOICES))

    def __post_init__(self) -> None:
        self.kind = BlockKind.HITL
        super().__post_init__()
        # Block stays "live" until the user resolves it; finalize() called
        # by the controller after the prompt returns.

    def render(self, width: int) -> RenderableType:
        header = Text()
        header.append(f"{GLYPHS.DOT} ", style="console.dot.warning")
        header.append(self.tool_name, style="console.tool.name")
        if self.summary:
            header.append(" · ", style="console.tool.duration")
            header.append(self.summary, style="console.tool.arg")

        warn_line = Text("  ")
        warn_line.append(f"{GLYPHS.WARNING} {self.tag}", style="console.hitl.warn")

        body = Text()
        for choice in self.choices:
            body.append("\n   ")
            body.append(choice.key, style="console.hitl.choice_key")
            body.append("  ")
            body.append(choice.label, style="console.hitl.choice_text")

        prompt_line = Text("\n  ❯ _", style="dim")
        return Group(header, warn_line, body, prompt_line)
