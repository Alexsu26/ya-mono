"""Todo list block — checkbox-style progress."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rich.console import Group, RenderableType
from rich.text import Text

from yaacli.console.blocks.base import BaseBlock, BlockKind
from yaacli.console.glyphs import GLYPHS

TodoStatus = Literal["pending", "in_progress", "completed"]


@dataclass
class TodoItem:
    content: str
    status: TodoStatus = "pending"


@dataclass
class TodoBlock(BaseBlock):
    """A snapshot of the agent's TodoWrite list."""

    items: list[TodoItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.kind = BlockKind.TODO
        super().__post_init__()
        self.state.is_terminal = True

    @property
    def done_count(self) -> int:
        return sum(1 for i in self.items if i.status == "completed")

    def render(self, width: int) -> RenderableType:
        header = Text()
        header.append(f"{GLYPHS.DOT} ", style="console.dot")
        header.append("Todos", style="console.tool.name")
        header.append(" · ", style="console.tool.duration")
        header.append(f"{self.done_count}/{len(self.items)}", style="console.tool.arg")

        body = Text()
        for item in self.items:
            body.append("  ")
            if item.status == "completed":
                body.append(f"{GLYPHS.CHECK}  ", style="console.todo.done")
                body.append(item.content + "\n", style="console.todo.done")
            elif item.status == "in_progress":
                body.append(f"{GLYPHS.PROGRESS}  ", style="console.todo.in_progress")
                body.append(item.content + "\n", style="console.todo.in_progress")
            else:
                body.append(f"{GLYPHS.EMPTY}  ", style="console.todo.pending")
                body.append(item.content + "\n", style="console.todo.pending")
        return Group(header, body)
