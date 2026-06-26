"""Tests for the event adapter that translates SDK stream events to the console.

Phase 2/3 sanity: feed canned StreamEvent-shaped objects through ConsoleSession
and confirm the matching ConsoleApp methods get called in the right order.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pytest
from rich.console import Console
from yaacli.console.app import ConsoleApp
from yaacli.console.theme import build_theme


@dataclass
class _FakeStreamEvent:
    """Mimics StreamEvent's outer shape: it has an .event attribute."""

    event: object


@pytest.fixture
def console_app() -> ConsoleApp:
    app = ConsoleApp(cwd=Path.cwd(), model_name="opus-4.7", mode="ACT")
    buf = io.StringIO()
    app.console = Console(theme=build_theme(), file=buf, width=100, force_terminal=False)
    from yaacli.console.stream import LiveStream

    app.stream = LiveStream(app.console)
    return app


def test_session_handles_text_part_start_and_delta(console_app: ConsoleApp) -> None:
    from pydantic_ai.messages import PartDeltaEvent, PartEndEvent, PartStartEvent, TextPart, TextPartDelta
    from yaacli.console_app import ConsoleSession

    session = ConsoleSession(sink=console_app)
    console_app.open_turn()
    session.handle(_FakeStreamEvent(event=PartStartEvent(index=0, part=TextPart(content="hello"))))
    session.handle(_FakeStreamEvent(event=PartDeltaEvent(index=0, delta=TextPartDelta(content_delta=" world"))))
    session.handle(_FakeStreamEvent(event=PartEndEvent(index=0, part=TextPart(content="hello world"))))
    console_app.close_turn()

    out = console_app.console.file.getvalue()
    assert "hello" in out
    assert "world" in out


def test_session_handles_tool_call_lifecycle(console_app: ConsoleApp) -> None:
    from pydantic_ai.messages import (
        FunctionToolCallEvent,
        FunctionToolResultEvent,
        ToolCallPart,
        ToolReturnPart,
    )
    from yaacli.console_app import ConsoleSession

    session = ConsoleSession(sink=console_app)
    console_app.open_turn()
    call = ToolCallPart(tool_name="Bash", args={"command": "ls"}, tool_call_id="t1")
    session.handle(_FakeStreamEvent(event=FunctionToolCallEvent(part=call)))

    return_part = ToolReturnPart(tool_name="Bash", content="file1\nfile2\n", tool_call_id="t1")
    session.handle(_FakeStreamEvent(event=FunctionToolResultEvent(result=return_part)))
    console_app.close_turn()

    out = console_app.console.file.getvalue()
    assert "Bash" in out
    assert "ls" in out
    # Result line: either summary or content fragment
    assert "file1" in out or "file" in out


def test_session_marks_tool_error_when_result_is_error_string(console_app: ConsoleApp) -> None:
    from pydantic_ai.messages import (
        FunctionToolCallEvent,
        FunctionToolResultEvent,
        ToolCallPart,
        ToolReturnPart,
    )
    from yaacli.console_app import ConsoleSession

    session = ConsoleSession(sink=console_app)
    console_app.open_turn()
    call = ToolCallPart(tool_name="Bash", args={"command": "false"}, tool_call_id="t9")
    session.handle(_FakeStreamEvent(event=FunctionToolCallEvent(part=call)))

    return_part = ToolReturnPart(
        tool_name="Bash",
        content="Tool execution error: nonzero exit",
        tool_call_id="t9",
    )
    session.handle(_FakeStreamEvent(event=FunctionToolResultEvent(result=return_part)))
    console_app.close_turn()

    out = console_app.console.file.getvalue()
    assert "✗" in out
    assert "failed" in out


def test_session_ignores_unknown_event_kinds(console_app: ConsoleApp) -> None:
    from yaacli.console_app import ConsoleSession

    session = ConsoleSession(sink=console_app)
    console_app.open_turn()
    session.handle(_FakeStreamEvent(event=object()))
    console_app.close_turn()
    # No raise = pass


def test_session_handles_compact_breadcrumbs(console_app: ConsoleApp) -> None:
    from ya_agent_sdk.events import CompactCompleteEvent, CompactStartEvent
    from yaacli.console_app import ConsoleSession

    session = ConsoleSession(sink=console_app)
    session.handle(_FakeStreamEvent(event=CompactStartEvent(event_id="evt1", message_count=10)))
    session.handle(
        _FakeStreamEvent(
            event=CompactCompleteEvent(
                event_id="evt2",
                original_message_count=10,
                compacted_message_count=4,
                summary_markdown="ok",
            )
        )
    )
    out = console_app.console.file.getvalue()
    assert "compacting" in out
    assert "compacted" in out
    assert "10" in out and "4" in out
