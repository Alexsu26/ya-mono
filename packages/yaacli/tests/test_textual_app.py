"""Pilot-driven smoke tests for the Textual v2 app."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import RichLog


def _make_stub_config() -> SimpleNamespace:
    """Build a minimal YaacliConfig-shaped object for the app."""
    return SimpleNamespace(
        general=SimpleNamespace(
            max_requests=10,
            agent_stream_resume_on_error=False,
            agent_stream_resume_max_attempts=0,
            agent_stream_resume_prompt="",
        ),
        models={},
    )


def _make_stub_runtime() -> Any:
    """Build a minimal runtime stub that supports send_message + steering_messages."""
    runtime = MagicMock()
    runtime.ctx = MagicMock()
    runtime.ctx.steering_messages = []
    runtime.ctx.send_message = MagicMock()
    return runtime


def _log_text(log: RichLog) -> str:
    return "\n".join("".join(seg.text for seg in strip) for strip in log.lines)


def _render_plain(renderable: object, *, width: int = 120) -> str:
    from rich.console import Console

    console = Console(width=width, force_terminal=False, color_system=None)
    return "".join(segment.text for segment in console.render(renderable))


@pytest.mark.asyncio
async def test_textualsink_streaming_text_writes_directly_to_richlog() -> None:
    """Streaming deltas write straight into RichLog history; LivePane stays empty."""
    from textual.app import App, ComposeResult
    from yaacli.console.textual_app import TextualSink
    from yaacli.console.widgets import LivePane

    class HarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=True, markup=False)
            yield LivePane()

    app = HarnessApp()
    async with app.run_test() as pilot:
        log = app.query_one(RichLog)
        live = app.query_one(LivePane)
        sink = TextualSink(log, live)

        sink.handle_text_delta("hello ")
        sink.handle_text_delta("world")
        await pilot.pause(0.1)
        # Text appears IN the log immediately, not in LivePane.
        assert not live.has_blocks
        assert len(log.lines) > 0

        sink.end_text()
        await pilot.pause(0.05)
        # end_text doesn't change history — text was already there.
        assert len(log.lines) > 0


@pytest.mark.asyncio
async def test_textualsink_streaming_never_shows_raw_markdown_markers() -> None:
    """Regression: while streaming, the user must never see raw ``##`` /
    ``**bold**`` / ``- `` markers that haven't been rendered yet.

    We feed a chunked Markdown response and snapshot the rendered log
    after every delta. None of those snapshots should contain raw markers.
    """
    from textual.app import App, ComposeResult
    from yaacli.console.textual_app import TextualSink
    from yaacli.console.widgets import LivePane

    class HarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=True, markup=False)
            yield LivePane()

    app = HarnessApp()
    async with app.run_test(size=(80, 30)) as pilot:
        log = app.query_one(RichLog)
        sink = TextualSink(log, app.query_one(LivePane))

        # Realistic chunked Markdown stream — final chunk closes the **bold.
        chunks = [
            "# ",
            "Title\n\n",
            "## ",
            "Section\n\n",
            "Some ",
            "**bold ",
            "text**",
            " here.\n",
            "- ",
            "first ",
            "item\n",
            "- ",
            "second item with **emph**asis\n",
        ]
        bad_frames: list[tuple[str, str]] = []
        for chunk in chunks:
            sink.handle_text_delta(chunk)
            await pilot.pause(0.01)
            content = "\n".join("".join(seg.text for seg in strip) for strip in log.lines)
            for marker in ("# ", "## ", "**bold", "**emph"):
                if marker in content:
                    bad_frames.append((chunk, marker))

        sink.end_text()
        await pilot.pause(0.02)
        final = "\n".join("".join(seg.text for seg in strip) for strip in log.lines)
        # After end, well-formed Markdown means no raw markers anywhere.
        assert "## " not in final, f"Final has raw heading marker: {final!r}"
        assert "**" not in final, f"Final has raw bold marker: {final!r}"

        if bad_frames:
            sample = "; ".join(f"after {c!r} saw {m!r}" for c, m in bad_frames[:3])
            raise AssertionError(f"{len(bad_frames)} streaming frames had raw markers: {sample}")


@pytest.mark.asyncio
async def test_textualsink_end_text_replaces_streamed_text_with_markdown() -> None:
    """``end_text`` re-renders the full buffer once as Markdown.

    During streaming the text is plain (no inline ``**bold**`` etc.); on
    flush we pop everything we wrote and emit a single Markdown render of
    the full buffer. This is the only place we redraw a multi-line region.
    """
    from textual.app import App, ComposeResult
    from yaacli.console.textual_app import TextualSink
    from yaacli.console.widgets import LivePane

    class HarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=True, markup=False)
            yield LivePane()

    app = HarnessApp()
    async with app.run_test() as pilot:
        log = app.query_one(RichLog)
        sink = TextualSink(log, app.query_one(LivePane))

        # Two streamed lines with inline-Markdown markers.
        sink.handle_text_delta("hello\n")
        sink.handle_text_delta("**world**")
        await pilot.pause(0.02)
        plain_streaming_lines = len(log.lines)
        assert plain_streaming_lines >= 1

        sink.end_text()
        await pilot.pause(0.05)

        # After end_text the log still contains rendered content (we don't
        # know the exact strip count for Markdown but it must be > 0).
        assert len(log.lines) > 0
        # Idempotent: calling again is a no-op.
        sink.end_text()
        await pilot.pause(0.02)


@pytest.mark.asyncio
async def test_textualsink_end_text_does_not_double_render_wrapped_lines() -> None:
    """Regression: when streaming a long line that wraps to multiple strips,
    ``end_text`` must pop ALL of them before re-rendering as Markdown.

    Previously we tracked logical line counts (``content.count('\\n')``) and
    popped that many strips — wrapped strips were left behind, so the user
    saw both the plain streaming version AND the Markdown version of the
    same line.
    """
    from textual.app import App, ComposeResult
    from yaacli.console.textual_app import TextualSink
    from yaacli.console.widgets import LivePane

    class HarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=True, markup=False)
            yield LivePane()

    # Narrow width forces wrapping.
    app = HarnessApp()
    async with app.run_test(size=(40, 20)) as pilot:
        log = app.query_one(RichLog)
        sink = TextualSink(log, app.query_one(LivePane))

        # One logical line, ~120 chars → wraps to 3+ strips at width 40.
        long_line = "lorem ipsum " * 12 + "\n"
        sink.handle_text_delta(long_line)
        await pilot.pause(0.02)

        # End and confirm the strip count is reasonable — if the bug were
        # back we'd see roughly 2x the expected lines.
        sink.end_text()
        await pilot.pause(0.05)

        # The Markdown render of one paragraph at width 40 should produce
        # ~3-5 strips (paragraph + maybe a trailing blank). The bug would
        # produce ~6-10. We assert a tight upper bound to catch regression.
        assert len(log.lines) <= 6, (
            f"end_text did not fully pop streamed plain text — got {len(log.lines)} strips, expected ≤6"
        )


@pytest.mark.asyncio
async def test_textualsink_streaming_rewrite_invalidates_render_cache() -> None:
    """Regression: streaming rewrites must repaint without focusing the log.

    Textual's RichLog caches ``render_line`` output by y/scroll/width. The
    sink mutates ``log.lines`` directly for in-place streaming, so it must
    invalidate that cache when replacing existing strips. Otherwise the
    terminal keeps showing the previous partial render until focus changes.
    """
    from textual.app import App, ComposeResult
    from textual.strip import Strip
    from yaacli.console.textual_app import TextualSink
    from yaacli.console.widgets import LivePane

    def strip_text(strip: Strip) -> str:
        return "".join(segment.text for segment in strip)

    class HarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=True, markup=False)
            yield LivePane()

    app = HarnessApp()
    async with app.run_test(size=(80, 20)) as pilot:
        log = app.query_one(RichLog)
        sink = TextualSink(log, app.query_one(LivePane))

        sink.handle_text_delta("foo")
        await pilot.pause(0.02)
        assert "foo" in _log_text(log)

        sink.handle_text_delta("bar")
        await pilot.pause(0.02)

        assert "foobar" in _log_text(log)


@pytest.mark.asyncio
async def test_textualsink_batches_small_streaming_deltas() -> None:
    """Small token deltas should not force a full Markdown render per token."""
    from textual.app import App, ComposeResult
    from yaacli.console.textual_app import TextualSink
    from yaacli.console.widgets import LivePane

    class HarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=True, markup=False)
            yield LivePane()

    app = HarnessApp()
    async with app.run_test(size=(80, 20)) as pilot:
        log = app.query_one(RichLog)
        sink = TextualSink(log, app.query_one(LivePane))
        render_count = 0
        original_render = sink._render_streaming_buffer

        def counted_render() -> None:
            nonlocal render_count
            render_count += 1
            original_render()

        sink._render_streaming_buffer = counted_render  # type: ignore[method-assign]

        for _ in range(40):
            sink.handle_text_delta("x")
        await pilot.pause(0.02)

        assert render_count < 40
        sink.end_text()
        await pilot.pause(0.02)
        assert "x" * 40 in _log_text(log)


@pytest.mark.asyncio
async def test_streaming_markdown_reflows_when_terminal_resizes() -> None:
    """Streaming text should follow terminal width changes before end_text.

    The sink renders streaming Markdown into RichLog strips itself. If the
    terminal is resized mid-stream, the current block must be re-rendered
    from the raw stream buffer rather than leaving old-width strips until
    the next model token arrives.
    """
    from yaacli.console.textual_app import YaacliTextualApp

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)
        long_text = (
            "## Resize Check\n\n"
            + "This streaming paragraph is intentionally long enough to wrap "
            + "only after the terminal becomes much narrower. "
            + "It includes **bold** text and `inline_code` so Markdown is active."
        )

        app._sink.handle_text_delta(long_text)
        await pilot.pause(0.05)
        wide_line_count = len(log.lines)

        await pilot.resize_terminal(42, 24)
        await pilot.pause(0.1)

        assert len(log.lines) > wide_line_count
        assert all(strip.cell_length <= 40 for strip in log.lines)


@pytest.mark.asyncio
async def test_textualsink_prunes_old_history_when_line_cap_is_reached() -> None:
    from textual.app import App, ComposeResult
    from yaacli.console.textual_app import TextualSink
    from yaacli.console.widgets import LivePane

    class HarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=True, markup=False)
            yield LivePane()

    app = HarnessApp()
    async with app.run_test(size=(80, 12)) as pilot:
        log = app.query_one(RichLog)
        sink = TextualSink(log, app.query_one(LivePane), max_log_lines=8)

        for i in range(30):
            sink.show_breadcrumb(f"line {i}")
        await pilot.pause(0.05)

        assert len(log.lines) <= 8
        text = _log_text(log)
        assert "line 29" in text
        assert "line 0" not in text
        assert all(entry.line_start >= 0 for entry in sink._history_entries)


@pytest.mark.asyncio
async def test_textualsink_handles_cjk_markdown_code_and_tables() -> None:
    """CJK, fenced code, and tables are common model output shapes."""
    from textual.app import App, ComposeResult
    from yaacli.console.textual_app import TextualSink
    from yaacli.console.widgets import LivePane

    class HarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=True, markup=False)
            yield LivePane()

    app = HarnessApp()
    async with app.run_test(size=(72, 24)) as pilot:
        log = app.query_one(RichLog)
        sink = TextualSink(log, app.query_one(LivePane))
        text = (
            "## 中文标题\n\n"
            "这是一段包含 **加粗文本**、`内联代码` 和较长中文内容的段落,用来覆盖宽字符换行。\n\n"
            "| 模块 | 状态 |\n| --- | --- |\n| yaacli | 正常 |\n\n"
            "```python\nprint('你好,世界')\n```\n"
        )

        for chunk in [text[i : i + 5] for i in range(0, len(text), 5)]:
            sink.handle_text_delta(chunk)
            await pilot.pause(0.005)
        sink.end_text()
        await pilot.pause(0.05)

        rendered = "\n".join("".join(seg.text for seg in strip) for strip in log.lines)
        assert "中文标题" in rendered
        assert "加粗文本" in rendered
        assert "内联代码" in rendered
        assert "yaacli" in rendered
        assert "print" in rendered
        assert "**" not in rendered


@pytest.mark.asyncio
async def test_long_streaming_output_stays_sticky_to_bottom_when_not_scrolled_up() -> None:
    """Large model output should keep following the tail by default."""
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import ScrollIndicator

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 18)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)
        indicator = app.query_one(ScrollIndicator)

        for i in range(80):
            app._sink.handle_text_delta(f"- streamed line {i}\n")
            await pilot.pause(0.002)
        app._sink.end_text()
        await pilot.pause()
        await pilot.pause()

        assert log.max_scroll_y > 0
        assert log.scroll_y >= max(0.0, log.max_scroll_y - 1.0)
        assert indicator.pending == 0


@pytest.mark.asyncio
async def test_textualsink_thinking_streams_in_richlog_then_commits() -> None:
    from textual.app import App, ComposeResult
    from yaacli.console.textual_app import TextualSink
    from yaacli.console.widgets import LivePane

    class HarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=True, markup=False)
            yield LivePane()

    app = HarnessApp()
    async with app.run_test() as pilot:
        log = app.query_one(RichLog)
        live = app.query_one(LivePane)
        sink = TextualSink(log, live)

        sink.handle_thinking_delta("reasoning…")
        await pilot.pause(0.05)
        assert not live.has_blocks
        assert "reasoning" in _log_text(log)
        first_render_lines = len(log.lines)

        sink.handle_thinking_delta(" more")
        await pilot.pause(0.05)
        assert not live.has_blocks
        assert "reasoning… more" in _log_text(log)
        assert len(log.lines) <= first_render_lines + 1

        sink.end_thinking()
        await pilot.pause(0.05)
        assert not live.has_blocks
        assert "reasoning… more" in _log_text(log)


@pytest.mark.asyncio
async def test_textualsink_render_width_reserves_scrollbar_column() -> None:
    from textual.app import App, ComposeResult
    from yaacli.console.textual_app import TextualSink
    from yaacli.console.widgets import LivePane

    class HarnessApp(App[None]):
        CSS = "#log { padding: 1 2; overflow-y: auto; scrollbar-size-vertical: 1; }"

        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=True, markup=False)
            yield LivePane()

    app = HarnessApp()
    async with app.run_test(size=(80, 20)) as pilot:
        log = app.query_one(RichLog)
        sink = TextualSink(log, app.query_one(LivePane))

        for i in range(40):
            sink.show_breadcrumb(f"line {i}")
        await pilot.pause()

        assert log.show_vertical_scrollbar
        assert sink.width <= log.size.width - 1


@pytest.mark.asyncio
async def test_textualsink_tool_call_runs_in_richlog_then_commits_to_log() -> None:
    from textual.app import App, ComposeResult
    from yaacli.console.textual_app import TextualSink
    from yaacli.console.widgets import LivePane

    class HarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=True, markup=False)
            yield LivePane()

    app = HarnessApp()
    async with app.run_test() as pilot:
        log = app.query_one(RichLog)
        live = app.query_one(LivePane)
        sink = TextualSink(log, live)

        sink.handle_tool_call_start("t1", "Read", {"path": "x.py"})
        await pilot.pause(0.15)
        # Running state stays in the transcript, not in the input-adjacent LivePane.
        assert not live.has_blocks
        running = _log_text(log)
        assert "Read" in running
        assert "running" in running
        first_render_lines = len(log.lines)

        sink.handle_tool_call_complete("t1", "a\nb\nc\n", error=False)
        await pilot.pause(0.05)
        # Done state replaces the transient running render with committed history.
        assert not live.has_blocks
        done = _log_text(log)
        assert "3 lines" in done
        assert len(log.lines) <= first_render_lines + 3


@pytest.mark.asyncio
async def test_active_tool_and_subagent_spinner_frames_advance_in_transcript() -> None:
    from textual.app import App, ComposeResult
    from yaacli.console.glyphs import SPINNER_FRAMES
    from yaacli.console.textual_app import TextualSink
    from yaacli.console.widgets import LivePane

    class HarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=True, markup=False)
            yield LivePane()

    app = HarnessApp()
    async with app.run_test():
        log = app.query_one(RichLog)
        sink = TextualSink(log, app.query_one(LivePane))

        sink.handle_tool_call_start("t1", "Read", {"path": "x.py"})
        sink.handle_subagent_start("sub1", "explorer")
        sink._stop_active_operations_timer()
        first_frame = _log_text(log)
        assert SPINNER_FRAMES[0] in first_frame
        assert "tool Read" in first_frame
        assert "subagent" in first_frame

        sink._tick_active_operations()
        sink._stop_active_operations_timer()
        second_frame = _log_text(log)
        assert SPINNER_FRAMES[1] in second_frame
        assert first_frame != second_frame


@pytest.mark.asyncio
async def test_app_layout_composes_all_widgets() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import (
        FooterHint,
        HeaderBar,
        LivePane,
        PromptArea,
        ScrollIndicator,
        SteeringList,
    )

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(HeaderBar) is not None
        assert app.query_one(RichLog) is not None
        assert app.query_one(LivePane) is not None
        assert app.query_one(SteeringList) is not None
        assert app.query_one(ScrollIndicator) is not None
        assert app.query_one(PromptArea) is not None
        assert app.query_one(FooterHint) is not None


@pytest.mark.asyncio
async def test_textual_launcher_disables_terminal_mouse_reporting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yaacli.console import textual_app

    class FakeAsyncResource:
        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    run_kwargs: list[dict[str, Any]] = []
    config = _make_stub_config()
    config.browser = SimpleNamespace()
    config_manager = SimpleNamespace(
        config_dir=tmp_path / ".yaacli",
        get_sessions_dir=lambda: tmp_path / ".yaacli" / "sessions",
        load_mcp_config=lambda: {},
    )

    monkeypatch.setattr(
        textual_app,
        "BrowserManager",
        lambda _browser_config: FakeAsyncResource(),
    )
    monkeypatch.setattr(
        textual_app,
        "create_tui_runtime",
        lambda **_kwargs: FakeAsyncResource(),
    )

    async def fake_run_async(self: Any, **kwargs: Any) -> None:
        run_kwargs.append(kwargs)

    monkeypatch.setattr(textual_app.YaacliTextualApp, "run_async", fake_run_async)

    await textual_app.run_textual_tui(
        config,
        config_manager,  # type: ignore[arg-type]
        working_dir=tmp_path,
    )

    assert run_kwargs
    assert run_kwargs[0].get("mouse") is False


@pytest.mark.asyncio
async def test_input_hints_explain_send_and_newline() -> None:
    from textual.app import App, ComposeResult
    from yaacli.console.widgets import FooterHint, PromptArea

    class HarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield FooterHint()

    prompt = PromptArea()
    assert "Enter sends" in str(prompt.placeholder)
    assert "Shift+Enter newline" in str(prompt.placeholder)

    app = HarnessApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one(FooterHint)
        rendered = str(footer.render())
        assert "Enter sends" in rendered
        assert "Shift+Enter newline" in rendered


@pytest.mark.asyncio
async def test_scroll_indicator_appears_when_scrolled_up_during_writes() -> None:
    """When the user scrolls up, new history bumps the ScrollIndicator
    and pauses auto_scroll."""
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import ScrollIndicator

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)
        indicator = app.query_one(ScrollIndicator)

        # Fill the log with enough content to make scrolling meaningful.
        for i in range(50):
            app._sink.show_breadcrumb(f"line {i}")
        await pilot.pause()
        assert log.max_scroll_y > 0, "log should overflow for this test"

        # Pretend the user scrolled up.
        log.scroll_to(y=0, animate=False)
        await pilot.pause()

        # Now write a new line — indicator should bump
        app._sink.show_breadcrumb("new arrival")
        # Two pauses: one for the write, one for call_after_refresh
        await pilot.pause()
        await pilot.pause()
        assert indicator.pending >= 1
        assert "new output below" in str(indicator.render())
        assert log.auto_scroll is False

        # End key restores stickiness
        app.action_scroll_to_bottom()
        await pilot.pause()
        assert indicator.pending == 0
        assert log.auto_scroll is True


@pytest.mark.asyncio
async def test_empty_prompt_up_down_scrolls_transcript_not_prompt_history() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)
        prompt = app.query_one(PromptArea)
        prompt.focus()
        app._prompt_history = ["previous prompt"]

        for i in range(40):
            app._sink.show_breadcrumb(f"scrollable line {i}")
        await pilot.pause()
        log.scroll_to(y=log.max_scroll_y, animate=False, immediate=True)
        await pilot.pause()
        bottom = log.scroll_y

        prompt.text = ""
        await pilot.press("up")
        await pilot.pause()

        assert prompt.text == ""
        assert log.scroll_y < bottom

        scrolled = log.scroll_y
        await pilot.press("down")
        await pilot.pause()

        assert prompt.text == ""
        assert log.scroll_y >= scrolled


@pytest.mark.asyncio
async def test_history_search_finds_assistant_tool_and_file_names() -> None:
    from yaacli.console.textual_app import YaacliTextualApp

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)

        app._sink.handle_text_delta("assistant mentions alpha keyword\n")
        app._sink.end_text()
        app._sink.handle_tool_call_start("t1", "Read", {"path": "src/target.py"})
        app._sink.handle_tool_call_complete("t1", "file body\n")
        await pilot.pause()

        assert app._search_history("alpha")
        assert app._search_history("Read")
        assert app._search_history("target.py")
        assert log.scroll_y >= 0


@pytest.mark.asyncio
async def test_jump_markers_move_between_assistant_tool_and_error() -> None:
    from yaacli.console.blocks import ErrorBlock
    from yaacli.console.textual_app import YaacliTextualApp

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)

        for i in range(12):
            app._sink.show_breadcrumb(f"filler {i}")
        app._sink.handle_text_delta("assistant block\n")
        app._sink.end_text()
        app._sink.handle_tool_call_start("t1", "Bash", {"command": "echo ok"})
        app._sink.handle_tool_call_complete("t1", "ok\n")
        app._sink.write_block(ErrorBlock(title="Boom", body="failure"))
        await pilot.pause()

        log.scroll_to(y=log.max_scroll_y, animate=False)
        await pilot.pause()

        assert app._jump_history_marker("assistant", -1)
        assistant_y = log.scroll_y
        assert app._jump_history_marker("tool", 1)
        tool_y = log.scroll_y
        assert app._jump_history_marker("error", 1)
        error_y = log.scroll_y
        assert assistant_y <= tool_y <= error_y


@pytest.mark.asyncio
async def test_jump_error_marker_includes_failed_tools() -> None:
    from yaacli.console.textual_app import YaacliTextualApp

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)

        for i in range(12):
            app._sink.show_breadcrumb(f"filler {i}")
        app._sink.handle_tool_call_start("t1", "Write", {"path": "src/fail.py"})
        app._sink.handle_tool_call_complete("t1", "permission denied", error=True)
        await pilot.pause()

        log.scroll_to(y=0, animate=False)
        await pilot.pause()

        assert app._jump_history_marker("error", 1)
        assert log.scroll_y > 0


@pytest.mark.asyncio
async def test_jump_previous_assistant_key_moves_viewport_off_bottom() -> None:
    from yaacli.console.blocks import UserPromptBlock
    from yaacli.console.textual_app import YaacliTextualApp

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)

        for i in range(20):
            app._sink.show_breadcrumb(f"before {i}")
        app._sink.write_block(UserPromptBlock(text="user jump target"))
        app._sink.handle_text_delta("assistant jump target\n")
        app._sink.end_text()
        assistant_entry = next(entry for entry in app._sink._history_entries if entry.kind == "assistant")
        user_entry = next(entry for entry in app._sink._history_entries if entry.kind == "user")
        for i in range(30):
            app._sink.show_breadcrumb(f"after {i}")
        await pilot.pause()

        log.scroll_to(y=log.max_scroll_y, animate=False)
        await pilot.pause()

        await pilot.press("alt+a")
        await pilot.pause()
        await pilot.pause()

        assert log.scroll_y <= assistant_entry.line_start + 1
        assert log.scroll_y < log.max_scroll_y
        assert log.auto_scroll is False

        log.scroll_to(y=log.max_scroll_y, animate=False)
        await pilot.pause()

        await pilot.press("alt+u")
        await pilot.pause()
        await pilot.pause()

        assert log.scroll_y <= user_entry.line_start + 1
        assert log.scroll_y < log.max_scroll_y
        assert log.auto_scroll is False


@pytest.mark.asyncio
async def test_jump_slash_command_keeps_target_visible() -> None:
    from yaacli.console.blocks import UserPromptBlock
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)
        prompt = app.query_one(PromptArea)
        prompt.focus()

        for i in range(20):
            app._sink.show_breadcrumb(f"before {i}")
        app._sink.write_block(UserPromptBlock(text="user slash target"))
        app._sink.handle_text_delta("assistant slash target\n")
        app._sink.end_text()
        assistant_entry = next(entry for entry in app._sink._history_entries if entry.kind == "assistant")
        user_entry = next(entry for entry in app._sink._history_entries if entry.kind == "user")
        for i in range(30):
            app._sink.show_breadcrumb(f"after {i}")
        await pilot.pause()

        log.scroll_to(y=log.max_scroll_y, animate=False)
        await pilot.pause()
        prompt.text = "/jump assistant"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        assert log.scroll_y <= assistant_entry.line_start + 1
        assert log.scroll_y < log.max_scroll_y
        assert log.auto_scroll is False

        log.scroll_to(y=log.max_scroll_y, animate=False)
        await pilot.pause()
        prompt.text = "/jump user"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        assert log.scroll_y <= user_entry.line_start + 1
        assert log.scroll_y < log.max_scroll_y
        assert log.auto_scroll is False


@pytest.mark.asyncio
async def test_jump_user_slash_command_does_not_target_itself() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)
        prompt = app.query_one(PromptArea)
        prompt.focus()

        prompt.text = "/jump user"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        assert "→ no user marker" in _log_text(log)
        assert "→ jumped to previous user" not in _log_text(log)


@pytest.mark.asyncio
async def test_textual_app_persists_renames_and_exports_session(
    tmp_path: Path,
) -> None:
    from yaacli.config import ConfigManager
    from yaacli.console.blocks import UserPromptBlock
    from yaacli.console.textual_app import YaacliTextualApp

    config = _make_stub_config()
    config.session = SimpleNamespace(
        auto_save_history=True,
        auto_restore=False,
        session_dir="",
    )
    config_manager = ConfigManager(config_dir=tmp_path / ".yaacli", project_dir=tmp_path)
    app = YaacliTextualApp(
        config=config,
        config_manager=config_manager,
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    export_path = tmp_path / "session.md"

    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        app._sink.write_block(UserPromptBlock(text="hello transcript"))
        app._sink.handle_text_delta("assistant transcript")
        app._sink.end_text()
        await pilot.pause(0.05)

        session_dir = config_manager.get_sessions_dir() / app.session_id
        assert (session_dir / "metadata.json").exists()
        assert (session_dir / "transcript.json").exists()

        await app._handle_command("/rename useful name\n/sessions")
        await app._handle_command(f"/export {export_path}")
        await pilot.pause(0.05)

    metadata = json.loads((session_dir / "metadata.json").read_text())
    assert metadata["name"] == "useful name"
    markdown = export_path.read_text()
    assert "hello transcript" in markdown
    assert "assistant transcript" in markdown
    assert "/rename useful name" not in markdown
    assert "/sessions" not in markdown


@pytest.mark.asyncio
async def test_textual_app_auto_names_session_from_first_user_prompt(
    tmp_path: Path,
) -> None:
    from yaacli.config import ConfigManager
    from yaacli.console.blocks import UserPromptBlock
    from yaacli.console.textual_app import YaacliTextualApp

    config = _make_stub_config()
    config.session = SimpleNamespace(
        auto_save_history=True,
        auto_restore=False,
        session_dir="",
    )
    config_manager = ConfigManager(config_dir=tmp_path / ".yaacli", project_dir=tmp_path)
    app = YaacliTextualApp(
        config=config,
        config_manager=config_manager,
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )

    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        app._sink.write_block(UserPromptBlock(text="first task\nwith detail"))
        app._sink.write_block(UserPromptBlock(text="latest follow-up"))
        await app._handle_command("/sessions")
        await pilot.pause(0.05)

        session_dir = config_manager.get_sessions_dir() / app.session_id
        rendered = _log_text(app.query_one(RichLog))

    metadata = json.loads((session_dir / "metadata.json").read_text())
    assert metadata["name"] == "first task"
    assert metadata["name_source"] == "auto"
    assert metadata["latest_user_prompt"] == "latest follow-up"

    assert "first task" in rendered
    assert "latest follow-up" in rendered


@pytest.mark.asyncio
async def test_textual_app_rename_takes_precedence_over_auto_session_name(
    tmp_path: Path,
) -> None:
    from yaacli.config import ConfigManager
    from yaacli.console.blocks import UserPromptBlock
    from yaacli.console.textual_app import YaacliTextualApp

    config = _make_stub_config()
    config.session = SimpleNamespace(
        auto_save_history=True,
        auto_restore=False,
        session_dir="",
    )
    config_manager = ConfigManager(config_dir=tmp_path / ".yaacli", project_dir=tmp_path)
    app = YaacliTextualApp(
        config=config,
        config_manager=config_manager,
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )

    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        app._sink.write_block(UserPromptBlock(text="first automatic task"))
        await app._handle_command("/rename explicit name")
        app._sink.write_block(UserPromptBlock(text="later task"))
        await pilot.pause(0.05)

        session_dir = config_manager.get_sessions_dir() / app.session_id

    metadata = json.loads((session_dir / "metadata.json").read_text())
    assert metadata["name"] == "explicit name"
    assert metadata["name_source"] == "explicit"
    assert metadata["latest_user_prompt"] == "later task"


@pytest.mark.asyncio
async def test_textual_app_sessions_fills_missing_name_from_transcript(
    tmp_path: Path,
) -> None:
    from yaacli.config import ConfigManager
    from yaacli.console.textual_app import YaacliTextualApp

    config = _make_stub_config()
    config.session = SimpleNamespace(
        auto_save_history=True,
        auto_restore=False,
        session_dir="",
    )
    config_manager = ConfigManager(config_dir=tmp_path / ".yaacli", project_dir=tmp_path)
    session_dir = config_manager.get_sessions_dir() / "abc123def456"
    session_dir.mkdir(parents=True)
    (session_dir / "metadata.json").write_text(
        json.dumps({
            "session_id": "abc123def456",
            "name": "",
            "working_dir": str(tmp_path),
            "created_at": "2026-05-14T00:00:00+00:00",
            "updated_at": "2026-05-14T00:00:01+00:00",
            "model": "opus-4.7",
            "turns": [],
            "tool_count": 0,
            "error_count": 0,
        })
    )
    (session_dir / "transcript.json").write_text(
        json.dumps([
            {"kind": "system", "text": "/sessions", "label": "/sessions"},
            {"kind": "user", "text": "first restored prompt", "label": "user"},
            {"kind": "assistant", "text": "restored assistant", "label": "assistant"},
            {"kind": "user", "text": "latest restored prompt", "label": "user"},
        ])
    )

    app = YaacliTextualApp(
        config=config,
        config_manager=config_manager,
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 20)) as pilot:
        await pilot.pause()
        await app._handle_command("/sessions")
        await pilot.pause(0.05)

        rendered = _log_text(app.query_one(RichLog))

    assert "first restored prompt" in rendered
    assert "latest restored prompt" in rendered
    for line in rendered.splitlines():
        if "abc123def456" in line:
            assert "(unnamed)" not in line


@pytest.mark.asyncio
async def test_textual_app_resume_restores_saved_transcript(tmp_path: Path) -> None:
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
    from yaacli.config import ConfigManager
    from yaacli.console.textual_app import YaacliTextualApp

    config = _make_stub_config()
    config.session = SimpleNamespace(
        auto_save_history=True,
        auto_restore=False,
        session_dir="",
    )
    config_manager = ConfigManager(config_dir=tmp_path / ".yaacli", project_dir=tmp_path)
    session_dir = config_manager.get_sessions_dir() / "abc123def456"
    session_dir.mkdir(parents=True)
    (session_dir / "metadata.json").write_text(
        json.dumps({
            "session_id": "abc123def456",
            "name": "saved",
            "working_dir": str(tmp_path),
            "created_at": "2026-05-14T00:00:00+00:00",
            "updated_at": "2026-05-14T00:00:01+00:00",
            "model": "opus-4.7",
            "turns": [],
            "tool_count": 0,
            "error_count": 0,
        })
    )
    (session_dir / "transcript.json").write_text(
        json.dumps([
            {"kind": "user", "text": "restored user", "label": "user"},
            {"kind": "assistant", "text": "restored assistant", "label": "assistant"},
        ])
    )
    (session_dir / "message_history.json").write_text("[]")

    app = YaacliTextualApp(
        config=config,
        config_manager=config_manager,
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        assert await app._handle_command("/resume abc123")
        await pilot.pause(0.05)

        assert app.session_id == "abc123def456"
        text = _log_text(app.query_one(RichLog))
        assert "restored user" in text
        assert "restored assistant" in text
        assert len(app._message_history) == 2
        restored_request = app._message_history[0]
        restored_response = app._message_history[1]
        assert isinstance(restored_request, ModelRequest)
        assert any(
            isinstance(part, UserPromptPart) and part.content == "restored user" for part in restored_request.parts
        )
        assert isinstance(restored_response, ModelResponse)
        assert any(
            isinstance(part, TextPart) and part.content == "restored assistant" for part in restored_response.parts
        )


@pytest.mark.asyncio
async def test_textual_app_load_replaces_stale_message_history_and_context(tmp_path: Path) -> None:
    from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, ModelResponse, TextPart, UserPromptPart
    from ya_agent_sdk.context import ResumableState
    from yaacli.config import ConfigManager
    from yaacli.console.textual_app import YaacliTextualApp

    config = _make_stub_config()
    config.session = SimpleNamespace(
        auto_save_history=True,
        auto_restore=False,
        session_dir="",
    )
    runtime = _make_stub_runtime()
    runtime.ctx.steering_messages = ["old steering"]
    config_manager = ConfigManager(config_dir=tmp_path / ".yaacli", project_dir=tmp_path)
    app = YaacliTextualApp(
        config=config,
        config_manager=config_manager,
        runtime=runtime,
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    load_dir = tmp_path / "dump"
    load_dir.mkdir()
    (load_dir / "metadata.json").write_text(
        json.dumps({
            "session_id": "dumped123",
            "name": "dumped",
            "working_dir": str(tmp_path),
            "created_at": "2026-05-14T00:00:00+00:00",
            "updated_at": "2026-05-14T00:00:01+00:00",
            "model": "opus-4.7",
            "turns": [],
            "tool_count": 0,
            "error_count": 0,
        })
    )
    (load_dir / "transcript.json").write_text(
        json.dumps([
            {"kind": "user", "text": "loaded user", "label": "user"},
            {"kind": "assistant", "text": "loaded assistant", "label": "assistant"},
        ])
    )

    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        assert app._transcript is not None
        stale_messages = [ModelRequest(parts=[UserPromptPart(content="stale user")])]
        app._transcript.message_history_path.write_bytes(ModelMessagesTypeAdapter.dump_json(stale_messages, indent=2))
        app._transcript.context_state_path.write_text(
            ResumableState(steering_messages=["old steering"]).model_dump_json(indent=2)
        )

        assert await app._handle_command(f"/load {load_dir}")
        await pilot.pause(0.05)

        assert not app._transcript.message_history_path.exists()
        assert not app._transcript.context_state_path.exists()
        assert runtime.ctx.steering_messages == []
        assert len(app._message_history) == 2
        restored_request = app._message_history[0]
        restored_response = app._message_history[1]
        assert isinstance(restored_request, ModelRequest)
        assert any(
            isinstance(part, UserPromptPart) and part.content == "loaded user" for part in restored_request.parts
        )
        assert isinstance(restored_response, ModelResponse)
        assert any(
            isinstance(part, TextPart) and part.content == "loaded assistant" for part in restored_response.parts
        )
        rendered = _log_text(app.query_one(RichLog))
        assert "loaded user" in rendered
        assert "stale user" not in rendered


@pytest.mark.asyncio
async def test_tool_keyboard_actions_toggle_details_and_copy_payloads() -> None:
    from yaacli.console.textual_app import YaacliTextualApp

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)
        details = app.query_one("#tool_details", RichLog)
        copied: list[str] = []
        app.copy_to_clipboard = copied.append  # type: ignore[method-assign]

        app._sink.handle_text_delta("assistant response stays in history\n")
        app._sink.end_text()
        app._sink.handle_tool_call_start(
            "t1",
            "Bash",
            {"command": "echo ok", "cwd": "/repo"},
        )
        app._sink.handle_tool_call_complete(
            "t1",
            {"stdout": "ok\n", "stderr": "", "exit_code": 0, "cwd": "/repo"},
        )
        await pilot.pause()
        assert "stdout" not in _log_text(log)

        await pilot.press("ctrl+o")
        await pilot.pause()
        assert log.display is False
        assert details.display is True
        assert "assistant response stays in history" not in _log_text(details)
        assert "stdout" in _log_text(details)
        assert "ok" in _log_text(details)

        await pilot.press("ctrl+o")
        await pilot.pause()
        assert log.display is True
        assert details.display is False
        assert "assistant response stays in history" in _log_text(log)

        app.action_tool_copy_command()
        app.action_tool_copy_output()
        assert copied[0] == "echo ok"
        assert "ok" in copied[1]


@pytest.mark.asyncio
async def test_tool_keyboard_actions_toggle_edit_diff_details(tmp_path: Path) -> None:
    from yaacli.console.blocks import EditBlock
    from yaacli.console.textual_app import YaacliTextualApp

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)
        details = app.query_one("#tool_details", RichLog)
        block = EditBlock.single(
            str(tmp_path / "x.py"),
            "def foo():\n    return 1\n",
            "def foo():\n    return 2\n",
        )
        block.expanded = False

        app._sink.write_block(block)
        await pilot.pause()
        assert "1 hunk" in _log_text(log)
        assert "+    return 2" not in _log_text(log)

        await pilot.press("ctrl+o")
        await pilot.pause()
        assert log.display is False
        assert details.display is True
        assert "+    return 2" in _log_text(details)
        assert "+    return 2" not in _log_text(log)


@pytest.mark.asyncio
async def test_help_command_writes_into_log() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)
        before = len(log.lines)

        prompt = app.query_one(PromptArea)
        prompt.text = "/help"
        prompt.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert len(log.lines) > before


@pytest.mark.asyncio
async def test_clear_command_empties_the_log() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)
        prompt = app.query_one(PromptArea)
        prompt.focus()

        prompt.text = "/help"
        await pilot.press("enter")
        await pilot.pause()
        assert len(log.lines) > 0

        prompt.text = "/clear"
        await pilot.press("enter")
        await pilot.pause()
        # /clear empties then writes a single breadcrumb line.
        assert len(log.lines) <= 2


@pytest.mark.asyncio
async def test_clear_command_removes_persisted_history_and_context(tmp_path: Path) -> None:
    from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, UserPromptPart
    from ya_agent_sdk.context import ResumableState
    from yaacli.config import ConfigManager
    from yaacli.console.textual_app import YaacliTextualApp

    config = _make_stub_config()
    config.session = SimpleNamespace(
        auto_save_history=True,
        auto_restore=False,
        session_dir="",
    )
    runtime = _make_stub_runtime()
    runtime.ctx.steering_messages = ["old steering"]
    config_manager = ConfigManager(config_dir=tmp_path / ".yaacli", project_dir=tmp_path)
    app = YaacliTextualApp(
        config=config,
        config_manager=config_manager,
        runtime=runtime,
        cwd=tmp_path,
        model_name="opus-4.7",
    )

    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        assert app._transcript is not None
        app._message_history = [ModelRequest(parts=[UserPromptPart(content="old user")])]
        app._transcript.message_history_path.write_bytes(
            ModelMessagesTypeAdapter.dump_json(app._message_history, indent=2)
        )
        app._transcript.context_state_path.write_text(
            ResumableState(steering_messages=["old steering"]).model_dump_json(indent=2)
        )

        assert await app._handle_command("/clear")
        await pilot.pause(0.05)

        assert app._message_history == []
        assert not app._transcript.message_history_path.exists()
        assert not app._transcript.context_state_path.exists()
        assert runtime.ctx.steering_messages == []
        assert app.has_session_data is False


@pytest.mark.asyncio
async def test_act_plan_toggle_updates_footer() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import FooterHint, PromptArea

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one(FooterHint)
        prompt = app.query_one(PromptArea)
        prompt.focus()

        prompt.text = "/plan"
        await pilot.press("enter")
        await pilot.pause()
        assert footer.mode == "PLAN"

        prompt.text = "/act"
        await pilot.press("enter")
        await pilot.pause()
        assert footer.mode == "ACT"


@pytest.mark.asyncio
async def test_steering_injects_when_agent_task_running() -> None:
    """Mid-run input goes to ctx.send_message + steering pane, not a new turn."""
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea, SteeringList

    runtime = _make_stub_runtime()

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=runtime,
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test() as pilot:
        await pilot.pause()

        async def _sleep_forever() -> None:
            await asyncio.sleep(60)

        app._agent_task = asyncio.create_task(_sleep_forever())
        await pilot.pause()

        prompt = app.query_one(PromptArea)
        prompt.focus()
        prompt.text = "please answer in Chinese"
        await pilot.press("enter")
        await pilot.pause()

        assert runtime.ctx.send_message.called
        bus_msg = runtime.ctx.send_message.call_args[0][0]
        assert bus_msg.content == "please answer in Chinese"

        steering = app.query_one(SteeringList)
        assert "please answer in Chinese" in steering.items
        assert steering.has_class("has-items")

        app._agent_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, BaseException):
            await app._agent_task


@pytest.mark.asyncio
async def test_ctrl_c_idle_first_press_warns_then_exits() -> None:
    from yaacli.console.textual_app import YaacliTextualApp

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)

        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running
        assert len(log.lines) > 0

        await pilot.press("ctrl+c")
        await pilot.pause(0.05)


@pytest.mark.asyncio
async def test_ctrl_c_during_run_cancels_task() -> None:
    from yaacli.console.textual_app import YaacliTextualApp

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test() as pilot:
        await pilot.pause()

        async def _sleep_forever() -> None:
            await asyncio.sleep(60)

        app._agent_task = asyncio.create_task(_sleep_forever())
        await pilot.pause()

        await pilot.press("ctrl+c")
        await pilot.pause(0.1)

        assert app._agent_task.cancelled() or app._agent_task.done()
        assert app.is_running


@pytest.mark.asyncio
async def test_escape_during_run_cancels_task() -> None:
    from yaacli.console.textual_app import YaacliTextualApp

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test() as pilot:
        await pilot.pause()

        async def _sleep_forever() -> None:
            await asyncio.sleep(60)

        app._agent_task = asyncio.create_task(_sleep_forever())
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause(0.1)

        assert app._agent_task.cancelled() or app._agent_task.done()
        assert app.is_running


@pytest.mark.asyncio
async def test_ctrl_c_after_cancelling_run_does_not_immediately_exit() -> None:
    from yaacli.console.textual_app import YaacliTextualApp

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test() as pilot:
        await pilot.pause()

        async def _sleep_forever() -> None:
            await asyncio.sleep(60)

        app._agent_task = asyncio.create_task(_sleep_forever())
        await pilot.pause()

        await pilot.press("ctrl+c")
        await pilot.pause(0.1)
        assert app._agent_task.cancelled() or app._agent_task.done()

        await pilot.press("ctrl+c")
        await pilot.pause(0.05)

        assert app.is_running
        assert "→ press Ctrl+C again to exit" in _log_text(app.query_one(RichLog))


@pytest.mark.asyncio
async def test_slash_menu_opens_on_slash_and_filters_by_typed_prefix() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea, SlashMenu

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(SlashMenu)
        prompt.focus()

        await pilot.press("slash")
        await pilot.pause()
        assert menu.is_open
        assert len(menu.visible_commands) > 5  # at least most defaults

        await pilot.press("h")
        await pilot.pause()
        assert menu.is_open
        names = [c.name for c in menu.visible_commands]
        assert "help" in names
        # Filter is applied: only commands starting with 'h'
        assert all(n.startswith("h") for n in names)

        await pilot.press("escape")
        await pilot.pause()
        assert not menu.is_open
        assert prompt.text == ""


@pytest.mark.asyncio
async def test_slash_menu_completes_with_tab() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea, SlashMenu

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(SlashMenu)
        prompt.focus()

        await pilot.press("slash", "h")
        await pilot.pause()
        assert menu.visible_commands  # menu populated

        # Tab completes the highlighted command
        await pilot.press("tab")
        await pilot.pause()
        assert prompt.text == "/help"


@pytest.mark.asyncio
async def test_prompt_history_up_down_restores_submitted_prompts_and_draft() -> None:
    """Submitted prompts should be available through Up/Down history keys.

    The current draft is restored after walking past the newest history item,
    which matches the behaviour users expect from coding-agent TUIs.
    """
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )

    async def fake_run_turn(_prompt: str) -> None:
        return None

    app._run_turn = fake_run_turn  # type: ignore[method-assign]

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        prompt.focus()

        prompt.text = "first prompt"
        await pilot.press("enter")
        await pilot.pause(0.05)
        prompt.text = "second prompt"
        await pilot.press("enter")
        await pilot.pause(0.05)

        prompt.text = "draft in progress"
        await pilot.press("up")
        await pilot.pause()
        assert prompt.text == "second prompt"

        await pilot.press("up")
        await pilot.pause()
        assert prompt.text == "first prompt"

        await pilot.press("down")
        await pilot.pause()
        assert prompt.text == "second prompt"

        await pilot.press("down")
        await pilot.pause()
        assert prompt.text == "draft in progress"


@pytest.mark.asyncio
async def test_prompt_history_deduplicates_consecutive_submissions() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )

    async def fake_run_turn(_prompt: str) -> None:
        return None

    app._run_turn = fake_run_turn  # type: ignore[method-assign]

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        prompt.focus()

        prompt.text = "same prompt"
        await pilot.press("enter")
        await pilot.pause(0.05)
        prompt.text = "same prompt"
        await pilot.press("enter")
        await pilot.pause(0.05)

        assert app._prompt_history == ["same prompt"]


@pytest.mark.asyncio
async def test_slash_menu_searches_descriptions_and_shows_param_hints() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea, SlashMenu

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(SlashMenu)
        prompt.focus()

        prompt.text = "/profile"
        await pilot.pause()

        names = [cmd.name for cmd in menu.visible_commands]
        assert "model" in names
        rendered = str(menu.render())
        assert "/model" in rendered
        assert "[name]" in rendered


@pytest.mark.asyncio
async def test_slash_completion_adds_space_for_commands_with_params() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea, SlashMenu

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(SlashMenu)
        prompt.focus()

        await pilot.press("slash", "m", "o")
        await pilot.pause()
        assert menu.visible_commands

        await pilot.press("tab")
        await pilot.pause()
        assert prompt.text == "/model "


def test_slash_palette_includes_skill_subagent_and_mcp_commands() -> None:
    from yaacli.console.palette import DEFAULT_COMMANDS

    command_names = {command.name for command in DEFAULT_COMMANDS}

    assert {
        "skills",
        "skill",
        "subagents",
        "subagent",
        "delegate",
        "spawn",
        "mcp",
    } <= command_names


@pytest.mark.asyncio
async def test_skill_slash_commands_list_and_show_details(tmp_path: Path) -> None:
    from yaacli.config import ConfigManager
    from yaacli.console.textual_app import YaacliTextualApp

    skill_dir = tmp_path / "skills" / "repo-map"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: repo-map
description: Map repository structure before changing code.
---

# Repo Map
""",
        encoding="utf-8",
    )
    config = _make_stub_config()
    config.session = SimpleNamespace(auto_save_history=False, session_dir="")
    config_manager = ConfigManager(config_dir=tmp_path / ".yaacli", project_dir=tmp_path)
    app = YaacliTextualApp(
        config=config,
        config_manager=config_manager,
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )

    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        assert await app._handle_command("/skills repo")
        assert await app._handle_command("/skill repo-map")
        await pilot.pause(0.05)

        rendered = _log_text(app.query_one(RichLog))

    assert "repo-map" in rendered
    assert "Map repository structure before changing code." in rendered
    assert "skills/repo-map" in rendered


@pytest.mark.asyncio
async def test_subagent_slash_commands_list_and_show_details(tmp_path: Path) -> None:
    from yaacli.config import ConfigManager, SubagentOverride, SubagentsConfig
    from yaacli.console.textual_app import YaacliTextualApp

    subagents_dir = tmp_path / ".yaacli" / "subagents"
    subagents_dir.mkdir(parents=True)
    (subagents_dir / "explorer.md").write_text(
        """---
name: explorer
description: Explore the codebase and report concise findings.
tools:
  - Read
  - Grep
optional_tools: Bash
model: inherit
---

Inspect code without editing it.
""",
        encoding="utf-8",
    )
    config = _make_stub_config()
    config.session = SimpleNamespace(auto_save_history=False, session_dir="")
    config.subagents = SubagentsConfig(
        overrides={
            "explorer": SubagentOverride(
                model="oauth@codex:gpt-5.5",
                model_settings="openai_responses_high",
            )
        }
    )
    config_manager = ConfigManager(config_dir=tmp_path / ".yaacli", project_dir=tmp_path)
    app = YaacliTextualApp(
        config=config,
        config_manager=config_manager,
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )

    async with app.run_test(size=(140, 30)) as pilot:
        await pilot.pause()
        assert await app._handle_command("/subagents explorer")
        assert await app._handle_command("/subagent explorer")
        await pilot.pause(0.05)

        rendered = _log_text(app.query_one(RichLog))

    assert "explorer" in rendered
    assert "Explore the codebase and report concise findings." in rendered
    assert "oauth@codex:gpt-5.5" in rendered
    assert "openai_responses_high" in rendered
    assert "Read, Grep" in rendered
    assert "Bash" in rendered
    assert "explorer.md" in rendered


@pytest.mark.asyncio
async def test_mcp_slash_command_lists_configured_servers(tmp_path: Path) -> None:
    from yaacli.config import ConfigManager
    from yaacli.console.textual_app import YaacliTextualApp

    config_dir = tmp_path / ".yaacli"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text(
        """{
  "servers": {
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "description": "GitHub repository tools"
    },
    "docs": {
      "transport": "streamable_http",
      "url": "https://docs.example/mcp",
      "required": false,
      "description": "Documentation lookup"
    }
  }
}
""",
        encoding="utf-8",
    )
    config = _make_stub_config()
    config.session = SimpleNamespace(auto_save_history=False, session_dir="")
    config.tools = SimpleNamespace(need_approval_mcps=["github"])
    config_manager = ConfigManager(config_dir=config_dir, project_dir=tmp_path)
    app = YaacliTextualApp(
        config=config,
        config_manager=config_manager,
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )

    async with app.run_test(size=(240, 30)) as pilot:
        await pilot.pause()
        assert await app._handle_command("/mcp git")
        await pilot.pause(0.05)

        rendered = _log_text(app.query_one(RichLog))

    assert "github" in rendered
    assert "docs" not in rendered
    assert "required" in rendered
    assert "approval" in rendered
    assert "stdio" in rendered
    assert "npx -y @modelcontextprotocol/server-github" in rendered
    assert "GitHub repository tools" in rendered
    assert str(config_dir / "mcp.json") in rendered


@pytest.mark.asyncio
async def test_delegate_and_spawn_slash_commands_trigger_agent_prompts(
    tmp_path: Path,
) -> None:
    from yaacli.config import ConfigManager
    from yaacli.console.textual_app import YaacliTextualApp

    subagents_dir = tmp_path / ".yaacli" / "subagents"
    subagents_dir.mkdir(parents=True)
    (subagents_dir / "explorer.md").write_text(
        """---
name: explorer
description: Explore the codebase.
---

Inspect code without editing it.
""",
        encoding="utf-8",
    )
    config = _make_stub_config()
    config.session = SimpleNamespace(auto_save_history=False, session_dir="")
    config_manager = ConfigManager(config_dir=tmp_path / ".yaacli", project_dir=tmp_path)
    app = YaacliTextualApp(
        config=config,
        config_manager=config_manager,
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    prompts: list[str] = []

    async def fake_run_turn(prompt: str) -> None:
        prompts.append(prompt)

    app._run_turn = fake_run_turn  # type: ignore[method-assign]

    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        assert await app._handle_command("/delegate explorer inspect packages/yaacli")
        if app._agent_task is not None:
            await app._agent_task
        assert await app._handle_command("/spawn explorer inspect packages/ya-agent-sdk")
        if app._agent_task is not None:
            await app._agent_task
        await pilot.pause(0.05)

    assert len(prompts) == 2
    assert "delegate" in prompts[0]
    assert 'subagent_name="explorer"' in prompts[0]
    assert "inspect packages/yaacli" in prompts[0]
    assert "spawn_delegate" in prompts[1]
    assert 'subagent_name="explorer"' in prompts[1]
    assert "inspect packages/ya-agent-sdk" in prompts[1]


@pytest.mark.asyncio
async def test_spawn_slash_menu_completes_subagent_name(tmp_path: Path) -> None:
    from yaacli.config import ConfigManager
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea, SlashMenu

    subagents_dir = tmp_path / ".yaacli" / "subagents"
    subagents_dir.mkdir(parents=True)
    (subagents_dir / "explorer.md").write_text(
        """---
name: explorer
description: Local codebase exploration specialist.
---

Inspect code without editing it.
""",
        encoding="utf-8",
    )
    config = _make_stub_config()
    config.session = SimpleNamespace(auto_save_history=False, session_dir="")
    config_manager = ConfigManager(config_dir=tmp_path / ".yaacli", project_dir=tmp_path)
    app = YaacliTextualApp(
        config=config,
        config_manager=config_manager,
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )

    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(SlashMenu)
        prompt.focus()

        prompt.text = "/spawn "
        await pilot.pause()

        assert menu.is_open
        assert [item.name for item in menu.visible_commands] == ["explorer"]
        assert "Local codebase exploration specialist." in str(menu.render())

        await pilot.press("tab")
        await pilot.pause()

        assert prompt.text == "/spawn explorer "
        assert not menu.is_open

        prompt.text = "/delegate exp"
        await pilot.pause()

        assert menu.is_open
        assert [item.name for item in menu.visible_commands] == ["explorer"]

        await pilot.press("enter")
        await pilot.pause()

        assert prompt.text == "/delegate explorer "
        assert not menu.is_open


@pytest.mark.asyncio
async def test_model_slash_command_switches_active_runtime_profile() -> None:
    from yaacli.config import ModelProfileConfig, YaacliConfig
    from yaacli.console.textual_app import YaacliTextualApp

    gpt_profile = ModelProfileConfig(
        model="gateway@openai-responses:openrouter-openai-gpt-5.4",
        model_settings="openai_default",
        model_cfg="gpt5_1m",
    )
    config = YaacliConfig(
        models={
            "opus-4.7": ModelProfileConfig(model="gateway@anthropic:gcp-claude-opus-4-7"),
            "gpt-5.4": gpt_profile,
        }
    )
    app = YaacliTextualApp(
        config=config,
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7 (gateway@anthropic:gcp-claude-opus-4-7)",
    )

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        with patch("yaacli.console.textual_app.apply_model_profile") as apply_profile:
            apply_profile.return_value = SimpleNamespace(context_window=1_000_000)
            handled = await app._handle_command("/model gpt-5.4")

        assert handled is True
        apply_profile.assert_called_once_with(app._runtime, gpt_profile)
        assert app._active_model_name == "gpt-5.4"
        assert app._model_name == ("gpt-5.4 (gateway@openai-responses:openrouter-openai-gpt-5.4)")
        assert app._footer.model_label == "gpt-5.4"

        await app._handle_command("/model")
        await pilot.pause()
        rendered = _log_text(app.query_one(RichLog))
        assert "gpt-5.4" in rendered
        assert "gateway@openai-responses:openrouter-openai-gpt-5.4" in rendered


@pytest.mark.asyncio
async def test_model_slash_command_shows_error_when_profile_apply_fails() -> None:
    from yaacli.config import ModelProfileConfig, YaacliConfig
    from yaacli.console.textual_app import YaacliTextualApp

    config = YaacliConfig(
        models={
            "opus-4.7": ModelProfileConfig(model="gateway@anthropic:gcp-claude-opus-4-7"),
            "gpt-5.4": ModelProfileConfig(model="openai-chat:gpt-5.4"),
        }
    )
    app = YaacliTextualApp(
        config=config,
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7 (gateway@anthropic:gcp-claude-opus-4-7)",
    )

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        with patch("yaacli.console.textual_app.apply_model_profile", side_effect=RuntimeError("boom")):
            handled = await app._handle_command("/model gpt-5.4")
        await pilot.pause()

        assert handled is True
        assert app._active_model_name == "opus-4.7"
        assert app._model_name == "opus-4.7 (gateway@anthropic:gcp-claude-opus-4-7)"
        rendered = _log_text(app.query_one(RichLog))
        assert "model switch failed" in rendered
        assert "boom" in rendered


@pytest.mark.asyncio
async def test_model_current_uses_configured_profile_when_display_uses_label() -> None:
    from yaacli.config import GeneralConfig, ModelProfileConfig, YaacliConfig
    from yaacli.console.textual_app import YaacliTextualApp

    config = YaacliConfig(
        general=GeneralConfig(active_model="subs-codex"),
        model_profiles={
            "subs-codex": ModelProfileConfig(
                label="Subs Codex (OpenAI)",
                model="oauth@codex:gpt-5.5",
                model_settings="openai_responses_high",
                model_cfg="gpt5_270k",
            )
        },
    )
    app = YaacliTextualApp(
        config=config,
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="Subs Codex (OpenAI) (oauth@codex:gpt-5.5)",
    )

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        handled = await app._handle_command("/model current")
        await pilot.pause()

        assert handled is True
        assert app._active_model_name == "subs-codex"
        rendered = _log_text(app.query_one(RichLog))
        assert "active model profile is unavailable" not in rendered
        assert "subs-codex" in rendered
        assert "Subs Codex (OpenAI)" in rendered
        assert "oauth@codex:gpt-5.5" in rendered


@pytest.mark.asyncio
async def test_model_slash_command_rejects_switch_while_agent_is_running() -> None:
    from yaacli.config import ModelProfileConfig, YaacliConfig
    from yaacli.console.textual_app import YaacliTextualApp

    config = YaacliConfig(
        models={
            "opus-4.7": ModelProfileConfig(model="gateway@anthropic:gcp-claude-opus-4-7"),
            "gpt-5.4": ModelProfileConfig(model="openai-chat:gpt-5.4"),
        }
    )
    app = YaacliTextualApp(
        config=config,
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7 (gateway@anthropic:gcp-claude-opus-4-7)",
    )

    async def _sleep_forever() -> None:
        await asyncio.sleep(60)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._agent_task = asyncio.create_task(_sleep_forever())
        try:
            with patch("yaacli.console.textual_app.apply_model_profile") as apply_profile:
                await app._handle_command("/model gpt-5.4")

            apply_profile.assert_not_called()
            assert app._active_model_name == "opus-4.7"
            assert app._model_name == ("opus-4.7 (gateway@anthropic:gcp-claude-opus-4-7)")
        finally:
            app._agent_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await app._agent_task


@pytest.mark.asyncio
async def test_slash_enter_for_required_param_command_completes_without_submitting() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        prompt.focus()

        await pilot.press("slash", "l", "o")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert prompt.text == "/load "
        assert app._prompt_history == []


@pytest.mark.asyncio
async def test_slash_menu_keeps_stable_order_after_recent_command() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea, SlashMenu

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(SlashMenu)
        prompt.focus()

        prompt.text = "/help"
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press("slash")
        await pilot.pause()

        assert menu.visible_commands
        assert [cmd.name for cmd in menu.visible_commands[:3]] == [
            "act",
            "plan",
            "clear",
        ]
        assert "RECENT" not in str(menu.render())


@pytest.mark.asyncio
async def test_slash_menu_resets_selection_when_filter_changes() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea, SlashMenu

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(SlashMenu)
        prompt.focus()

        await pilot.press("slash")
        await pilot.pause()
        for _ in range(4):
            await pilot.press("down")
        await pilot.pause()
        assert menu.selected_index == 4

        await pilot.press("s")
        await pilot.pause()

        assert menu.selected_index == 0
        assert menu.selected_command.name == "session"


@pytest.mark.asyncio
async def test_slash_menu_keeps_keyboard_selection_inside_rendered_window() -> None:
    """Long slash palettes should not let the selection move off-screen."""
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea, SlashMenu

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(SlashMenu)
        prompt.focus()
        commands = tuple(
            SimpleNamespace(
                name=f"cmd{i:02d}",
                group="OTHER",
                description=f"Command {i:02d}",
                params=(),
                shortcut=None,
            )
            for i in range(menu.MAX_RENDERED_ROWS + 6)
        )
        menu.set_all_commands(commands)

        await pilot.press("slash")
        await pilot.pause()
        assert len(menu.visible_commands) > menu.MAX_RENDERED_ROWS

        for _ in range(menu.MAX_RENDERED_ROWS + 3):
            await pilot.press("down")
        await pilot.pause()

        rendered = str(menu.render())
        rendered_lines = rendered.splitlines()
        assert len(rendered_lines) <= menu.MAX_RENDERED_ROWS
        assert sum(line.startswith("▸ ") for line in rendered_lines) == 1
        assert f"/{menu.selected_command.name}" in rendered


@pytest.mark.asyncio
async def test_path_mention_menu_filters_workspace_paths(tmp_path: Path) -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PathMentionMenu, PromptArea

    (tmp_path / "packages" / "yaacli").mkdir(parents=True)
    (tmp_path / "packages" / "yaacli" / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "README.md").write_text("# demo\n")

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(PathMentionMenu)
        prompt.focus()

        prompt.text = "inspect @packages/yaa"
        prompt.move_cursor((0, len(prompt.text)), select=False)
        await pilot.pause()

        assert menu.is_open
        labels = [item.display for item in menu.visible_items]
        assert "packages/yaacli/" in labels


@pytest.mark.asyncio
async def test_path_mention_menu_resets_selection_when_filter_changes(tmp_path: Path) -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PathMentionMenu, PromptArea

    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / "bravo").mkdir()

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(PathMentionMenu)
        prompt.focus()

        await pilot.press("at")
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("down")
        await pilot.pause()
        assert menu.selected_index == 2

        await pilot.press("b")
        await pilot.pause()

        assert menu.selected_index == 0
        assert menu.selected_item is not None
        assert menu.selected_item.display == "beta/"


@pytest.mark.asyncio
async def test_path_mention_at_opens_workspace_root(tmp_path: Path) -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PathMentionMenu, PromptArea

    (tmp_path / "packages").mkdir()
    (tmp_path / "README.md").write_text("# demo\n")

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(PathMentionMenu)
        prompt.focus()

        await pilot.press("at")
        await pilot.pause()

        labels = [item.display for item in menu.visible_items]
        assert "packages/" in labels
        assert "README.md" in labels


@pytest.mark.asyncio
async def test_path_mention_pack_prefix_opens_packages(tmp_path: Path) -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PathMentionMenu, PromptArea

    (tmp_path / "packages").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\n")

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(PathMentionMenu)
        prompt.focus()

        await pilot.press("at", "p", "a", "c", "k")
        await pilot.pause()

        labels = [item.display for item in menu.visible_items]
        assert labels == ["packages/"]


@pytest.mark.asyncio
async def test_path_mention_menu_renders_above_prompt_area(tmp_path: Path) -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PathMentionMenu, PromptArea

    (tmp_path / "packages").mkdir()

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 25)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(PathMentionMenu)
        prompt.focus()

        await pilot.press("at", "p", "a", "c", "k")
        await pilot.pause()

        assert menu.visible_items
        assert menu.region.y + menu.region.height <= prompt.region.y


@pytest.mark.asyncio
async def test_path_mention_completion_replaces_current_token(tmp_path: Path) -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PathMentionMenu, PromptArea

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n")

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(PathMentionMenu)
        prompt.focus()

        prompt.text = "open @src/ma"
        prompt.move_cursor((0, len(prompt.text)), select=False)
        await pilot.pause()
        assert menu.visible_items

        await pilot.press("tab")
        await pilot.pause()
        assert prompt.text == "open @src/main.py "


@pytest.mark.asyncio
async def test_path_mention_completion_works_from_key_input(tmp_path: Path) -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PathMentionMenu, PromptArea

    (tmp_path / "packages" / "yaacli").mkdir(parents=True)

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(PathMentionMenu)
        prompt.focus()

        await pilot.press(
            "at",
            "p",
            "a",
            "c",
            "k",
            "a",
            "g",
            "e",
            "s",
            "slash",
            "y",
            "a",
            "a",
        )
        await pilot.pause()
        assert menu.is_open

        await pilot.press("tab")
        await pilot.pause()
        assert prompt.text == "@packages/yaacli/"


@pytest.mark.asyncio
async def test_path_mention_tab_refreshes_candidates_before_completion(tmp_path: Path) -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PathMentionMenu, PromptArea

    (tmp_path / "packages" / "yaacli").mkdir(parents=True)

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        menu = app.query_one(PathMentionMenu)
        prompt.focus()

        prompt.text = "@packages/yaa"
        prompt.move_cursor((0, len(prompt.text)), select=False)
        menu.update_query("")
        assert not menu.is_open

        await pilot.press("tab")
        await pilot.pause()
        assert prompt.text == "@packages/yaacli/"


@pytest.mark.asyncio
async def test_submit_injects_file_mention_context(tmp_path: Path) -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    (tmp_path / "notes.md").write_text("important context\n")
    captured: list[str] = []

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=tmp_path,
        model_name="opus-4.7",
    )

    async def fake_run_turn(prompt: str) -> None:
        captured.append(prompt)

    app._run_turn = fake_run_turn  # type: ignore[method-assign]

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        prompt.focus()

        prompt.text = "summarize @notes.md please"
        prompt.move_cursor((0, len(prompt.text)), select=False)
        await pilot.press("enter")
        await pilot.pause(0.05)

        assert captured
        assert "summarize @notes.md please" in captured[0]
        assert '<mentioned-file path="notes.md">' in captured[0]
        assert "important context" in captured[0]


@pytest.mark.asyncio
async def test_status_bar_transitions_idle_thinking_tool_text() -> None:
    """StatusBar reflects active phase: idle → thinking → tool → text → idle.

    Each transition is driven by a TextualSink call (matches the SDK
    event adapter's behaviour).
    """
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import StatusBar

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        status = app.query_one(StatusBar)
        assert status.state == "idle"

        # Tool start → state=tool, detail includes name
        app._sink.handle_tool_call_start("t1", "Bash", {"command": "ls"})
        await pilot.pause(0.02)
        assert status.state == "tool"
        assert "Bash" in status.detail

        # Tool done → idle
        app._sink.handle_tool_call_complete("t1", "result\n")
        await pilot.pause(0.02)
        assert status.state == "idle"

        # Thinking
        app._sink.handle_thinking_delta("…")
        await pilot.pause(0.02)
        assert status.state == "thinking"
        app._sink.end_thinking()
        await pilot.pause(0.02)
        assert status.state == "idle"

        # Text streaming
        app._sink.handle_text_delta("hi")
        await pilot.pause(0.02)
        assert status.state == "text"
        app._sink.end_text()
        await pilot.pause(0.02)
        assert status.state == "idle"


@pytest.mark.asyncio
async def test_status_bar_stays_waiting_while_turn_is_active_between_events() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import StatusBar

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        status = app.query_one(StatusBar)
        app._footer.state = "working"

        app._sink.handle_thinking_delta("deciding tool")
        await pilot.pause(0.02)
        app._sink.end_thinking()
        await pilot.pause(0.02)

        assert status.state == "waiting"
        assert "tool" in status.detail


def test_status_bar_uses_explicit_transcript_first_labels() -> None:
    from yaacli.console.widgets import StatusBar

    assert StatusBar.label_for_state("idle") == "ready"
    assert StatusBar.label_for_state("waiting") == "waiting for tool result"
    assert StatusBar.label_for_state("tool") == "running tool"
    assert StatusBar.label_for_state("text") == "streaming response"


@pytest.mark.asyncio
async def test_status_bar_context_usage_is_lightweight_and_thresholded() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import StatusBar

    assert StatusBar.context_style_for_pct(18) == "#6f778a"
    assert StatusBar.context_style_for_pct(70) == "#e0af68"
    assert StatusBar.context_style_for_pct(85) == "#e0af68"
    assert StatusBar.context_style_for_pct(85.1) == "#f7768e"

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        status = app.query_one(StatusBar)
        assert "ctx" not in _render_plain(status.render())

        status.context_pct = 18
        await pilot.pause(0.02)
        assert "ready · 18% ctx" in _render_plain(status.render())

        status.context_pct = 86
        await pilot.pause(0.02)
        assert "ready · 86% ctx · compact soon" in _render_plain(status.render())


@pytest.mark.asyncio
async def test_textual_app_sink_context_update_drives_status_bar() -> None:
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import StatusBar

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        status = app.query_one(StatusBar)

        app._sink.handle_context_update(180, 1000)
        await pilot.pause(0.02)
        assert status.context_pct == 18
        assert "ready · 18% ctx" in _render_plain(status.render())


@pytest.mark.asyncio
async def test_status_bar_repaints_to_layout_width_on_initial_mount() -> None:
    from rich.console import Console
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import StatusBar

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(200, 30)) as pilot:
        await pilot.pause()
        status = app.query_one(StatusBar)
        console = Console(width=240, force_terminal=False)
        rendered_width = sum(segment.cell_length for segment in console.render(status.render()))

        assert status.size.width >= 190
        assert rendered_width >= status.size.width - 4


@pytest.mark.asyncio
async def test_status_bar_is_always_visible() -> None:
    """The StatusBar is the visible separator between content and input —
    must always be in the DOM and rendered."""
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import StatusBar

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        status = app.query_one(StatusBar)
        # 1 cell tall, full width — visible separator
        assert status.size.height == 1
        assert status.size.width > 0


@pytest.mark.asyncio
async def test_multiline_prompt_expands_without_overlapping_status_or_footer() -> None:
    """Regression: bottom dock widgets used to overlap the prompt's last row,
    so the third and later input lines appeared swallowed by the footer/status.
    """
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import FooterHint, PromptArea, StatusBar

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        status = app.query_one(StatusBar)
        footer = app.query_one(FooterHint)
        prompt.focus()

        for key in (
            "o",
            "n",
            "e",
            "shift+enter",
            "t",
            "w",
            "o",
            "shift+enter",
            "t",
            "h",
            "r",
            "e",
            "e",
            "shift+enter",
            "f",
            "o",
            "u",
            "r",
            "shift+enter",
            "f",
            "i",
            "v",
            "e",
        ):
            await pilot.press(key)
        await pilot.pause()

        assert prompt.text == "one\ntwo\nthree\nfour\nfive"
        assert prompt.region.height >= 5
        assert status.region.y + status.region.height <= prompt.region.y
        assert prompt.region.y + prompt.region.height <= footer.region.y


@pytest.mark.asyncio
async def test_prompt_area_decodes_terminal_associated_text_sequences() -> None:
    """Regression: some terminals send IME commits as CSI-u associated text."""
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        prompt.focus()

        for character in "[32;;20013:25991u":
            prompt.insert(character)
            await pilot.pause()

        assert prompt.text == "中文"


@pytest.mark.asyncio
async def test_prompt_area_buffers_terminal_associated_text_keys_before_insert() -> None:
    """Raw CSI-u fragments must not become visible while the sequence arrives."""
    from textual.events import Key
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    def key_for(character: str) -> Key:
        key_names = {"^": "circumflex_accent", "[": "left_square_bracket", ";": "semicolon", ":": "colon"}
        return Key(key_names.get(character, character), character)

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        prompt.focus()

        for character in "^[32;;20013:25991u":
            await prompt._on_key(key_for(character))
            assert "[32;;" not in prompt.text
            assert "^" not in prompt.text

        assert prompt.text == "中文"


@pytest.mark.asyncio
async def test_prompt_area_flushes_literal_terminal_sequence_prefixes() -> None:
    from textual.events import Key
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        prompt.focus()

        await prompt._on_key(Key("left_square_bracket", "["))
        assert prompt.text == ""
        await pilot.pause(0.2)

        assert prompt.text == "["


def test_console_session_handles_tool_call_part_start_before_result() -> None:
    """Some SDK/model streams expose a ToolCallPart start before the result event."""
    from pydantic_ai.messages import PartStartEvent, ToolCallPart
    from ya_agent_sdk.context import StreamEvent
    from yaacli.console.adapter import ConsoleSession

    class Sink:
        def __init__(self) -> None:
            self.started: list[tuple[str, str, object]] = []

        def show_breadcrumb(self, text: str) -> None:
            raise AssertionError(text)

        def handle_text_delta(self, delta: str) -> None:
            raise AssertionError(delta)

        def end_text(self) -> None:
            pass

        def handle_thinking_delta(self, delta: str) -> None:
            raise AssertionError(delta)

        def end_thinking(self) -> None:
            pass

        def handle_tool_call_start(self, tool_call_id: str, name: str, args: object = None) -> None:
            self.started.append((tool_call_id, name, args))

        def handle_tool_call_complete(self, tool_call_id: str, result: object, *, error: bool = False) -> None:
            raise AssertionError(tool_call_id)

    sink = Sink()
    session = ConsoleSession(sink=sink)  # type: ignore[arg-type]
    session.handle(
        StreamEvent(
            agent_id="main",
            agent_name="main",
            event=PartStartEvent(
                index=0,
                part=ToolCallPart(
                    tool_call_id="call-1",
                    tool_name="Bash",
                    args={"command": "pwd"},
                ),
            ),
        )
    )

    assert sink.started == [("call-1", "Bash", {"command": "pwd"})]


def test_console_session_routes_context_update_event_to_sink() -> None:
    from ya_agent_sdk.context import StreamEvent
    from yaacli.console.adapter import ConsoleSession
    from yaacli.events import ContextUpdateEvent

    class Sink:
        def __init__(self) -> None:
            self.context_updates: list[tuple[int, int]] = []

        def show_breadcrumb(self, text: str) -> None:
            raise AssertionError(text)

        def handle_text_delta(self, delta: str) -> None:
            raise AssertionError(delta)

        def end_text(self) -> None:
            pass

        def handle_thinking_delta(self, delta: str) -> None:
            raise AssertionError(delta)

        def end_thinking(self) -> None:
            pass

        def handle_tool_call_start(self, tool_call_id: str, name: str, args: object = None) -> None:
            raise AssertionError(tool_call_id)

        def handle_tool_call_complete(self, tool_call_id: str, result: object, *, error: bool = False) -> None:
            raise AssertionError(tool_call_id)

        def handle_context_update(self, total_tokens: int, context_window_size: int) -> None:
            self.context_updates.append((total_tokens, context_window_size))

    sink = Sink()
    session = ConsoleSession(sink=sink)  # type: ignore[arg-type]
    session.handle(
        StreamEvent(
            agent_id="main",
            agent_name="main",
            event=ContextUpdateEvent(
                event_id="ctx-1",
                total_tokens=180,
                context_window_size=1000,
            ),
        )
    )

    assert sink.context_updates == [(180, 1000)]


def test_console_session_surfaces_encrypted_reasoning_without_summary() -> None:
    from pydantic_ai.messages import PartStartEvent, ThinkingPart
    from ya_agent_sdk.context import StreamEvent
    from yaacli.console.adapter import ConsoleSession

    class Sink:
        def __init__(self) -> None:
            self.thinking: list[str] = []

        def show_breadcrumb(self, text: str) -> None:
            raise AssertionError(text)

        def handle_text_delta(self, delta: str) -> None:
            raise AssertionError(delta)

        def end_text(self) -> None:
            pass

        def handle_thinking_delta(self, delta: str) -> None:
            self.thinking.append(delta)

        def end_thinking(self) -> None:
            pass

        def handle_tool_call_start(self, tool_call_id: str, name: str, args: object = None) -> None:
            raise AssertionError(tool_call_id)

        def handle_tool_call_complete(self, tool_call_id: str, result: object, *, error: bool = False) -> None:
            raise AssertionError(tool_call_id)

    sink = Sink()
    session = ConsoleSession(sink=sink)  # type: ignore[arg-type]
    session.handle(
        StreamEvent(
            agent_id="main",
            agent_name="main",
            event=PartStartEvent(
                index=0,
                part=ThinkingPart(
                    content="",
                    id="rs_1",
                    signature="encrypted",
                    provider_name="codex",
                ),
            ),
        )
    )

    assert sink.thinking == ["Reasoning was encrypted by the provider; no summary was returned."]


@pytest.mark.asyncio
async def test_subagent_tool_calls_collapsed_into_single_block() -> None:
    """Regression: the SDK emits subagent tool events on the main stream.
    They must NOT appear as top-level tool blocks in the user's log —
    only one collapsed progress block per subagent.
    """
    from pydantic_ai.messages import (
        FunctionToolCallEvent,
        FunctionToolResultEvent,
        ToolCallPart,
        ToolReturnPart,
    )
    from ya_agent_sdk.context import StreamEvent
    from ya_agent_sdk.events import SubagentCompleteEvent, SubagentStartEvent
    from yaacli.console.adapter import ConsoleSession
    from yaacli.console.textual_app import YaacliTextualApp

    def evt(agent_id: str, inner: object) -> StreamEvent:
        return StreamEvent(agent_id=agent_id, agent_name=agent_id, event=inner)

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        log = app.query_one(RichLog)
        session = ConsoleSession(sink=app._sink)

        baseline = len(log.lines)

        # Spawn a subagent + 5 tool calls inside it
        session.handle(
            evt(
                "main",
                SubagentStartEvent(
                    event_id="e1",
                    agent_id="sub1",
                    agent_name="explorer",
                    prompt_preview="explore",
                ),
            )
        )
        for i in range(5):
            session.handle(
                evt(
                    "sub1",
                    FunctionToolCallEvent(
                        part=ToolCallPart(
                            tool_name="Read",
                            args={"path": f"f{i}.py"},
                            tool_call_id=f"t{i}",
                        )
                    ),
                )
            )
            session.handle(
                evt(
                    "sub1",
                    FunctionToolResultEvent(
                        result=ToolReturnPart(
                            tool_name="Read",
                            content="ok",
                            tool_call_id=f"t{i}",
                        )
                    ),
                )
            )
        await pilot.pause(0.05)

        # During execution: progress stays in the transcript, not near the prompt.
        assert len(log.lines) > baseline
        running = _log_text(log)
        assert "subagent" in running
        assert "explorer" in running
        assert "5 tools" in running

        # Complete: ONE summary line in log, not 10 (5 tool calls + 5 results)
        session.handle(
            evt(
                "main",
                SubagentCompleteEvent(
                    event_id="e2",
                    agent_id="sub1",
                    agent_name="explorer",
                    success=True,
                    duration_seconds=1.5,
                ),
            )
        )
        await pilot.pause(0.05)
        new_lines = len(log.lines) - baseline
        assert new_lines == 1, f"expected 1 summary line, got {new_lines}"
        last = "".join(seg.text for seg in log.lines[-1])
        assert "subagent" in last
        assert "explorer" in last
        assert "5 tools" in last


@pytest.mark.asyncio
async def test_streaming_renders_correctly_with_focus_on_input() -> None:
    """Regression: previously, when the user kept focus on the prompt
    while the agent streamed Markdown, the RichLog did not repaint after
    pop+rewrite cycles (Textual's strip cache served stale lines).
    Forcing ``refresh(layout=True)`` is what makes the live render work.
    """
    from yaacli.console.textual_app import YaacliTextualApp
    from yaacli.console.widgets import PromptArea

    app = YaacliTextualApp(
        config=_make_stub_config(),
        runtime=_make_stub_runtime(),
        cwd=Path.cwd(),
        model_name="opus-4.7",
    )
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptArea)
        log = app.query_one(RichLog)
        prompt.focus()  # critical: focus on input, not log

        text = "## Heading\n\nPara with **bold** and `code`.\n\n- one\n- two\n- three\n"
        for chunk in [text[i : i + 6] for i in range(0, len(text), 6)]:
            app._sink.handle_text_delta(chunk)
            await pilot.pause(0.01)
        app._sink.end_text()
        await pilot.pause(0.05)

        rendered = "\n".join("".join(seg.text for seg in s) for s in log.lines)
        # No raw markers in final output
        assert "## " not in rendered
        assert "**bold**" not in rendered
        # Bullet got rendered
        assert "•" in rendered or "one" in rendered
