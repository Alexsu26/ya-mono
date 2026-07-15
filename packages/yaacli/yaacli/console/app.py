"""ConsoleApp — orchestrates the streaming console.

Phase 1: agent-agnostic. Drives the LiveStream from any source of blocks.
Phase 2 wires this to ya_agent_sdk.stream_agent via an adapter.

The contract:
- ``handle_text_delta(delta)`` — model text chunk
- ``handle_thinking_delta(delta)`` — thinking chunk
- ``handle_tool_call_start(tool_call_id, name, args)``
- ``handle_tool_call_complete(tool_call_id, result, error=False)``
- ``handle_user_prompt(text)`` / ``handle_breadcrumb(text)``
- ``open_turn()`` / ``close_turn()`` — bracket each agent run
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

from yaacli.console.blocks import (
    BreadcrumbBlock,
    EditBlock,
    ErrorBlock,
    HitlBlock,
    ModelTextBlock,
    SystemBlock,
    TaskBlock,
    TaskChild,
    ThinkingBlock,
    TodoBlock,
    TodoItem,
    ToolCallBlock,
    UserPromptBlock,
)
from yaacli.console.header import HeaderInfo, render_header
from yaacli.console.palette import DEFAULT_COMMANDS, SlashCommand
from yaacli.console.stream import LiveStream
from yaacli.console.theme import build_theme


@dataclass
class ConsoleApp:
    """Top-level orchestrator for the streaming console."""

    cwd: Path
    model_name: str | None = None
    mode: str = "ACT"
    commands: tuple[SlashCommand, ...] = field(default_factory=lambda: DEFAULT_COMMANDS)

    console: Console = field(init=False)
    stream: LiveStream = field(init=False)
    _current_text: ModelTextBlock | None = field(default=None, init=False)
    _current_thinking: ThinkingBlock | None = field(default=None, init=False)
    _tool_blocks: dict[str, ToolCallBlock] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.console = Console(theme=build_theme(), highlight=False, soft_wrap=False)
        self.stream = LiveStream(self.console)

    # -------- session-level surfaces -------------------------------------------

    def show_header(self) -> None:
        info = HeaderInfo.gather(self.cwd, self.model_name)
        self.console.print(render_header(info))
        self.console.print()

    def show_breadcrumb(self, text: str) -> None:
        block = BreadcrumbBlock(text=text)
        if self.stream.is_open:
            self.stream.print(block)
        else:
            self.console.print(block.render(self.console.size.width))

    def show_system(self, title: str, body: Any, *, boxed: bool = True) -> None:
        block = SystemBlock(title=title, body=body, boxed=boxed)
        if self.stream.is_open:
            self.stream.print(block)
        else:
            self.console.print(block.render(self.console.size.width))

    def show_error(self, title: str, body: str, *, detail: str = "") -> None:
        block = ErrorBlock(title=title, body=body, detail=detail)
        if self.stream.is_open:
            self.stream.print(block)
        else:
            self.console.print(block.render(self.console.size.width))

    def show_user_prompt(self, text: str) -> None:
        block = UserPromptBlock(text=text)
        # Always print user prompts straight to history — they bracket turns.
        self.console.print(block.render(self.console.size.width))

    # -------- turn boundaries ---------------------------------------------------

    def open_turn(self) -> None:
        self.stream.open()
        self._current_text = None
        self._current_thinking = None
        self._tool_blocks.clear()

    def close_turn(self) -> None:
        # Flush any in-flight tool blocks as terminal so they commit.
        for block in self._tool_blocks.values():
            if not block.is_terminal():
                block.complete(result="(no result)", error=False)
        self.stream.close()

    # -------- streaming primitives ---------------------------------------------

    def handle_text_delta(self, delta: str) -> None:
        if self._current_text is None:
            self._current_text = ModelTextBlock()
            self.stream.attach(self._current_text)
        self._current_text.append(delta)
        self.stream.update(self._current_text)

    def end_text(self) -> None:
        if self._current_text is None:
            return
        self._current_text.finalize()
        self.stream.commit(self._current_text)
        self._current_text = None

    def handle_thinking_delta(self, delta: str) -> None:
        if self._current_thinking is None:
            self._current_thinking = ThinkingBlock()
            self.stream.attach(self._current_thinking)
        self._current_thinking.append(delta)
        self.stream.update(self._current_thinking)

    def end_thinking(self) -> None:
        if self._current_thinking is None:
            return
        self._current_thinking.finalize()
        self.stream.commit(self._current_thinking)
        self._current_thinking = None

    def handle_tool_call_start(self, tool_call_id: str, name: str, args: Any = None) -> None:
        # Close any open text block so the tool block sits below it cleanly.
        self.end_text()
        block = ToolCallBlock(name=name, args=args)
        self._tool_blocks[tool_call_id] = block
        self.stream.attach(block)

    def handle_tool_args_update(self, tool_call_id: str, args: Any) -> None:
        block = self._tool_blocks.get(tool_call_id)
        if block is None:
            return
        block.update_args(args)
        self.stream.update(block)

    def handle_tool_call_complete(self, tool_call_id: str, result: Any, *, error: bool = False) -> None:
        block = self._tool_blocks.pop(tool_call_id, None)
        if block is None:
            return
        block.complete(result, error=error)
        self.stream.update(block)
        self.stream.commit(block)

    def handle_context_update(self, total_tokens: int, context_window_size: int) -> None:
        """No-op for the non-Textual console; v2 surfaces this in StatusBar."""
        return

    def handle_subagent_start(self, agent_id: str, name: str, prompt_preview: str = "") -> None:
        """Render a compact lifecycle breadcrumb for a background subagent."""
        self.show_breadcrumb(f"→ subagent {name} started ({agent_id})")

    def handle_subagent_progress(self, agent_id: str, tool_name: str, tool_count: int) -> None:
        """Keep background progress quiet in the modal console."""
        return

    def handle_subagent_complete(
        self,
        agent_id: str,
        *,
        success: bool = True,
        result_preview: str = "",
        duration_seconds: float = 0.0,
    ) -> None:
        """Render a compact completion breadcrumb for a background subagent."""
        state = "completed" if success else "failed"
        self.show_breadcrumb(f"→ subagent {agent_id} {state}")

    # -------- batch / one-shot blocks -------------------------------------------

    def show_edit(self, path: str, edits: Iterable[tuple[str, str]]) -> None:
        block = EditBlock(path=path, edits=list(edits))
        if self.stream.is_open:
            self.stream.print(block)
        else:
            self.console.print(block.render(self.console.size.width))

    def show_todos(self, items: Iterable[TodoItem]) -> None:
        block = TodoBlock(items=list(items))
        if self.stream.is_open:
            self.stream.print(block)
        else:
            self.console.print(block.render(self.console.size.width))

    def show_task(self, title: str, children: Iterable[TaskChild]) -> None:
        block = TaskBlock(title=title, children=list(children))
        # Tasks may include running children. Force terminal for one-shot show.
        block.state.is_terminal = True
        if self.stream.is_open:
            self.stream.print(block)
        else:
            self.console.print(block.render(self.console.size.width))

    def show_hitl(self, tool_name: str, summary: str, *, tag: str = "needs approval") -> HitlBlock:
        block = HitlBlock(tool_name=tool_name, summary=summary, tag=tag)
        if self.stream.is_open:
            self.stream.print(block)
        else:
            self.console.print(block.render(self.console.size.width))
        return block
