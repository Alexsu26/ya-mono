"""Block protocol — the unit the streaming console renders.

Blocks know how to render themselves. The LiveStream owns when they render.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from rich.console import RenderableType


class BlockKind(StrEnum):
    """Categorical kind for a block — used for filtering, telemetry, layout."""

    USER_PROMPT = "user_prompt"
    MODEL_TEXT = "model_text"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    EDIT = "edit"
    TODO = "todo"
    TASK = "task"
    ERROR = "error"
    HITL = "hitl"
    SYSTEM = "system"
    BREADCRUMB = "breadcrumb"


_BLOCK_ID_COUNTER = itertools.count(1)


def next_block_id(kind: BlockKind) -> str:
    """Generate a process-unique block id."""
    return f"{kind.value}-{next(_BLOCK_ID_COUNTER)}"


@dataclass
class BlockState:
    """Mutable state attached to every block."""

    is_terminal: bool = False
    error: bool = False


class Block(Protocol):
    """A block is anything that knows how to render itself.

    Blocks are mutable while attached to the live tail. Once a block reports
    ``is_terminal()`` true, the LiveStream commits it to history and stops
    re-rendering it.
    """

    block_id: str
    kind: BlockKind
    state: BlockState

    def render(self, width: int) -> RenderableType:
        """Render the block. ``width`` is the available terminal width."""
        ...

    def is_terminal(self) -> bool:
        """Return whether this block is finalized and ready for commit."""
        ...


@dataclass
class BaseBlock:
    """Convenience base — concrete blocks may inherit instead of duck-typing."""

    kind: BlockKind = field(init=False)
    block_id: str = field(init=False)
    state: BlockState = field(default_factory=BlockState, init=False)

    def __post_init__(self) -> None:
        # Subclasses set ``kind`` before invoking super().__post_init__().
        if not hasattr(self, "kind"):
            raise RuntimeError("BaseBlock subclass must set ``kind``")
        self.block_id = next_block_id(self.kind)

    def is_terminal(self) -> bool:
        return self.state.is_terminal

    def finalize(self, *, error: bool = False) -> None:
        self.state.is_terminal = True
        self.state.error = error
