"""Sub-agent / Task block — a parent ⏺ with ⏵ children."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rich.console import Group, RenderableType
from rich.spinner import Spinner
from rich.text import Text

from yaacli.console.blocks.base import BaseBlock, BlockKind
from yaacli.console.glyphs import GLYPHS

TaskChildStatus = Literal["running", "done", "error"]


@dataclass
class TaskChild:
    name: str
    detail: str = ""
    status: TaskChildStatus = "running"
    summary: str = ""
    duration: float = 0.0


@dataclass
class TaskBlock(BaseBlock):
    """Parent task block with N children."""

    title: str = ""
    children: list[TaskChild] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.kind = BlockKind.TASK
        super().__post_init__()

    def add_child(self, child: TaskChild) -> None:
        self.children.append(child)

    def update_child(self, idx: int, **kwargs: object) -> None:
        if 0 <= idx < len(self.children):
            child = self.children[idx]
            for k, v in kwargs.items():
                setattr(child, k, v)

    def render(self, width: int) -> RenderableType:
        header = Text()
        header.append(f"{GLYPHS.DOT} ", style="console.dot")
        header.append("Task", style="console.tool.name")
        if self.title:
            header.append(" · ", style="console.tool.duration")
            header.append(self.title, style="console.tool.arg")

        renderables: list[RenderableType] = [header]
        for child in self.children:
            line = Text("  ")
            line.append(f"{GLYPHS.BULLET_TASK} ", style="console.tool.spinner")
            line.append(child.name, style="console.tool.name")
            if child.detail:
                line.append(" · ", style="console.tool.duration")
                line.append(child.detail, style="console.tool.arg")
            renderables.append(line)

            if child.status == "running":
                run_line = Text("    ")
                run_line.append(f"{GLYPHS.L_BAR} ", style="console.lbar")
                run_line.append("running", style="console.tool.duration")
                renderables.append(Spinner("dots", text=run_line, style="console.tool.spinner"))
            else:
                result_line = Text("    ")
                result_line.append(f"{GLYPHS.L_BAR} ", style="console.lbar")
                if child.status == "error":
                    result_line.append(child.summary or "failed", style="console.dot.error")
                else:
                    result_line.append(child.summary or "done", style="console.tool.result")
                if child.duration:
                    result_line.append(f" · {child.duration:.1f}s", style="console.tool.duration")
                renderables.append(result_line)
        return Group(*renderables)
