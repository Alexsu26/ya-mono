"""Adapter — translates ya-agent-sdk stream events into block-sink calls.

The sink protocol is intentionally tiny so multiple front-ends (the modal
prompt fallback in ``console_app.py`` and the Textual app in
``console/textual_app.py``) can both consume the same SDK event stream.

Subagent handling
-----------------
The SDK merges all agent events (main + subagents) into a single stream,
each carrying ``agent_id``. Naive forwarding produces noise: a single
``delegate`` from main spawns a subagent that runs N tools, all of which
would appear as top-level tool blocks in the user's view.

We collapse non-main agents:

* On the FIRST tool call from a subagent, emit a single
  ``subagent_start(agent_id, name)`` to the sink (one stable line).
* Subsequent tool calls / text deltas / thinking from that subagent are
  suppressed (only the running count + last tool name on the stable line
  gets updated).
* On ``SubagentCompleteEvent`` (or when the agent_id stops appearing),
  the line is finalised with ``subagent_complete(agent_id, summary)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
)
from ya_agent_sdk.context import StreamEvent
from ya_agent_sdk.events import (
    CompactCompleteEvent,
    CompactStartEvent,
    HandoffCompleteEvent,
    HandoffStartEvent,
    SubagentCompleteEvent,
    SubagentStartEvent,
)

from yaacli.events import ContextUpdateEvent

HIDDEN_REASONING_NOTICE = (
    "Reasoning was encrypted by the provider; no summary was returned."
)


@runtime_checkable
class BlockSink(Protocol):
    """Anything ConsoleSession can write blocks to.

    Both ``yaacli.console.app.ConsoleApp`` (rich.live.Live based) and
    ``yaacli.console.textual_app.TextualSink`` satisfy this protocol.
    """

    def show_breadcrumb(self, text: str) -> None: ...
    def handle_text_delta(self, delta: str) -> None: ...
    def end_text(self) -> None: ...
    def handle_thinking_delta(self, delta: str) -> None: ...
    def end_thinking(self) -> None: ...
    def handle_tool_call_start(self, tool_call_id: str, name: str, args: Any = None) -> None: ...
    def handle_tool_call_complete(
        self, tool_call_id: str, result: Any, *, error: bool = False
    ) -> None: ...

    # Optional — sinks that can render a collapsed subagent progress line
    # should implement these. The default ConsoleApp sink falls back to
    # show_breadcrumb when these are absent.
    def handle_subagent_start(self, agent_id: str, name: str, prompt_preview: str = "") -> None: ...
    def handle_subagent_progress(self, agent_id: str, tool_name: str, tool_count: int) -> None: ...
    def handle_subagent_complete(
        self, agent_id: str, *, success: bool = True,
        result_preview: str = "", duration_seconds: float = 0.0,
    ) -> None: ...
    def handle_context_update(self, total_tokens: int, context_window_size: int) -> None: ...


def extract_tool_result_text(event: FunctionToolResultEvent) -> tuple[str, bool]:
    """Best-effort: get a string + error flag from a tool result event."""
    try:
        content = event.result.content
    except AttributeError:
        return ("", False)

    if content is None:
        return ("", False)
    if isinstance(content, str):
        is_error = content.startswith("Tool execution error")
        return (content, is_error)
    return (str(content), False)


def _safe_call(sink: Any, method: str, *args: Any, **kwargs: Any) -> bool:
    """Call a sink method if implemented, else no-op. Returns True if called."""
    fn = getattr(sink, method, None)
    if fn is None:
        return False
    try:
        fn(*args, **kwargs)
        return True
    except Exception:
        return False


@dataclass
class _SubagentState:
    """Per-subagent running state."""

    agent_id: str
    name: str
    tool_count: int = 0
    last_tool: str = ""


@dataclass
class ConsoleSession:
    """Translate ya-agent-sdk events into BlockSink calls.

    Subagent events are collapsed: only a single progress line per
    subagent is forwarded to the sink. See module docstring.
    """

    sink: BlockSink

    _saw_text: bool = field(default=False, init=False)
    _saw_thinking: bool = field(default=False, init=False)
    _subagents: dict[str, _SubagentState] = field(default_factory=dict, init=False)

    async def stream(self, events: Any) -> None:
        async for event in events:
            self.handle(event)

    def handle(self, event: StreamEvent) -> None:
        agent_id = getattr(event, "agent_id", "main") or "main"
        msg = getattr(event, "event", None)
        if msg is None:
            return

        # ---- Lifecycle: subagent start/complete are routed to the sink
        # regardless of which agent_id they came from (the SDK emits them
        # on the parent agent's stream).
        if isinstance(msg, SubagentStartEvent):
            sub_id = msg.agent_id
            self._subagents[sub_id] = _SubagentState(
                agent_id=sub_id, name=msg.agent_name or sub_id
            )
            if not _safe_call(
                self.sink, "handle_subagent_start",
                sub_id, msg.agent_name or sub_id, msg.prompt_preview,
            ):
                self.sink.show_breadcrumb(
                    f"→ subagent {msg.agent_name or sub_id} started"
                )
            return

        if isinstance(msg, SubagentCompleteEvent):
            sub_id = msg.agent_id
            self._subagents.pop(sub_id, None)
            if not _safe_call(
                self.sink, "handle_subagent_complete",
                sub_id,
                success=msg.success,
                result_preview=msg.result_preview,
                duration_seconds=msg.duration_seconds,
            ):
                status = "✓" if msg.success else "✗"
                self.sink.show_breadcrumb(
                    f"→ subagent {sub_id} {status} ({msg.duration_seconds:.1f}s)"
                )
            return

        # ---- All other events from non-main agents are collapsed to a
        # progress line update on the parent subagent block.
        if agent_id != "main" and agent_id in self._subagents:
            if isinstance(msg, FunctionToolCallEvent):
                state = self._subagents[agent_id]
                state.tool_count += 1
                state.last_tool = msg.part.tool_name
                _safe_call(
                    self.sink, "handle_subagent_progress",
                    agent_id, state.last_tool, state.tool_count,
                )
            # Everything else (text deltas, thinking, tool results) is
            # silently dropped — subagent's final answer flows through the
            # delegate tool's result, which the main agent will surface.
            return

        # ---- Main-agent events fall through to normal handling below.

        if isinstance(msg, ContextUpdateEvent):
            _safe_call(
                self.sink,
                "handle_context_update",
                msg.total_tokens,
                msg.context_window_size,
            )
            return

        # Streaming text deltas
        if isinstance(msg, PartStartEvent) and isinstance(msg.part, TextPart):
            self.sink.end_thinking()
            self.sink.end_text()
            if msg.part.content:
                self.sink.handle_text_delta(msg.part.content)
                self._saw_text = True
            return

        if isinstance(msg, PartStartEvent) and isinstance(msg.part, ThinkingPart):
            self.sink.end_text()
            self.sink.end_thinking()
            if msg.part.content:
                self.sink.handle_thinking_delta(msg.part.content)
                self._saw_thinking = True
            elif _thinking_part_is_hidden(msg.part):
                self.sink.handle_thinking_delta(HIDDEN_REASONING_NOTICE)
                self._saw_thinking = True
            return

        if isinstance(msg, PartStartEvent) and isinstance(msg.part, ToolCallPart):
            self.sink.end_text()
            self.sink.end_thinking()
            self.sink.handle_tool_call_start(
                msg.part.tool_call_id,
                msg.part.tool_name,
                msg.part.args,
            )
            return

        if isinstance(msg, PartDeltaEvent) and isinstance(msg.delta, TextPartDelta):
            delta = msg.delta.content_delta or ""
            if delta:
                self.sink.handle_text_delta(delta)
                self._saw_text = True
            return

        if isinstance(msg, PartDeltaEvent) and isinstance(msg.delta, ThinkingPartDelta):
            delta = msg.delta.content_delta or ""
            if delta:
                self.sink.handle_thinking_delta(delta)
                self._saw_thinking = True
            return

        if isinstance(msg, PartEndEvent):
            if isinstance(msg.part, TextPart):
                self.sink.end_text()
            elif isinstance(msg.part, ThinkingPart):
                self.sink.end_thinking()
            return

        if isinstance(msg, PartStartEvent):
            self.sink.end_text()
            self.sink.end_thinking()
            return

        # Tool calls (main agent only — subagent calls were filtered above)
        if isinstance(msg, FunctionToolCallEvent):
            self.sink.end_text()
            self.sink.end_thinking()
            self.sink.handle_tool_call_start(
                msg.part.tool_call_id,
                msg.part.tool_name,
                msg.part.args,
            )
            return

        if isinstance(msg, FunctionToolResultEvent):
            text, is_error = extract_tool_result_text(msg)
            self.sink.handle_tool_call_complete(msg.tool_call_id, text, error=is_error)
            return

        # Lifecycle breadcrumbs
        if isinstance(msg, CompactStartEvent):
            self.sink.show_breadcrumb("→ compacting message history…")
            return
        if isinstance(msg, CompactCompleteEvent):
            self.sink.show_breadcrumb(
                f"→ compacted {msg.original_message_count} → {msg.compacted_message_count} messages"
            )
            return
        if isinstance(msg, HandoffStartEvent):
            self.sink.show_breadcrumb("→ subagent handoff started")
            return
        if isinstance(msg, HandoffCompleteEvent):
            self.sink.show_breadcrumb("→ subagent handoff completed")
            return


def _thinking_part_is_hidden(part: ThinkingPart) -> bool:
    return bool(part.signature or part.provider_details) and not part.content
