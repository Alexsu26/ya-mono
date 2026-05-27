"""Textual-based v2 streaming console.

Layout:
    HeaderBar              dock=top
    RichLog (scrollable)   fills middle — committed history; streaming text
                                          writes IN PLACE here so the response
                                          grows from the bottom of scrollback
    SteeringList           dock=bottom — hidden when empty
    Input chrome           dock=bottom — StatusBar + multiline PromptArea +
                                          FooterHint laid out as one stack
    ScrollIndicator        floating overlay — "↓ N new lines" pill that
                                              appears when the user scrolls up
                                              while history is arriving

The app owns:
- runtime / browser via AsyncExitStack
- one ``_agent_task`` at a time
- mid-run input → ``ctx.send_message(...)`` (steering)
- single Ctrl+C cancels in-flight task; double Ctrl+C in 2s when idle exits
- scroll position watcher: pause auto_scroll when user scrolls up; restore
  on End / when user scrolls back to the bottom

Streaming model:
- Streaming model TEXT writes directly into the RichLog: each delta pops
  the previous render's strips and writes a fresh snapshot in place. The
  user sees the response grow incrementally at the bottom of scrollback.
- In-flight TOOL CALLS and SUBAGENTS also write a transient render into
  RichLog. On complete, the transient render is popped and the final block
  is committed to history. This keeps all run output attached to the
  transcript instead of appearing next to the prompt.
- THINKING streams in the RichLog like model text, so it grows at the
  transcript position instead of appearing from the input area upward.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolDenied, UsageLimits
from rich.console import Console as RichConsole
from rich.console import Group, RenderableType
from rich.segment import Segments
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, RichLog, Static
from ya_agent_sdk.agents.main import stream_agent
from ya_agent_sdk.context import BusMessage
from ya_agent_sdk.mcp import MCPConfig, MCPServerConfig, load_mcp_config_file

from yaacli.browser import BrowserManager
from yaacli.config import ConfigManager, YaacliConfig
from yaacli.console.adapter import ConsoleSession
from yaacli.console.blocks import (
    EditBlock,
    ErrorBlock,
    ModelTextBlock,
    SystemBlock,
    ThinkingBlock,
    ToolCallBlock,
    UserPromptBlock,
)
from yaacli.console.design import truncate_cells
from yaacli.console.discovery import (
    DiscoveredSkill,
    DiscoveredSubagent,
    discover_skills,
    discover_subagents,
)
from yaacli.console.glyphs import GLYPHS, SPINNER_FRAMES
from yaacli.console.header import HeaderInfo
from yaacli.console.theme import build_theme
from yaacli.console.transcript import TranscriptStore, new_session_id
from yaacli.console.widgets import (
    FooterHint,
    HeaderBar,
    LivePane,
    PathMentionMenu,
    PromptArea,
    ScrollIndicator,
    SlashMenu,
    StatusBar,
    SteeringList,
)
from yaacli.hooks import emit_context_update
from yaacli.logging import get_logger
from yaacli.runtime import apply_model_profile, create_tui_runtime

logger = get_logger(__name__)


class StreamingRichLog(RichLog):
    """RichLog variant that notifies the sink when visible width changes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.on_width_changed: Callable[[], None] | None = None

    def on_resize(self, event: Any) -> None:
        super().on_resize(event)
        if self.on_width_changed is not None:
            self.call_after_refresh(self.on_width_changed)


def _close_open_markdown_markers(text: str) -> str:
    """Append synthetic closers for unfinished inline Markdown markers.

    Streaming Markdown shows raw markers (``**``, ``` ` ```, ``*``, ``_``)
    until the closing pair arrives. This helper patches the *last*
    in-progress line so the user never sees raw mid-stream markers.

    Subtleties:
      * Markdown rejects ``**foo **`` (space immediately before the
        closer) as bold. So we strip trailing spaces from the line, add
        the synthetic closer, then re-append the trailing whitespace.
      * Earlier lines are committed Markdown blocks and don't need patching.
      * Code fences (``` ``` ```) and blockquotes are line-structural and
        Markdown handles them already; we only patch single-line inline pairs.
      * Underscore emphasis is rare in CJK content; skip to avoid false positives.
    """
    if not text:
        return text
    head, sep, last_line = text.rpartition("\n")
    # Split the last line into content + trailing whitespace so we can
    # insert the closer adjacent to a non-space character.
    stripped = last_line.rstrip()
    trailing = last_line[len(stripped) :]
    patched = stripped
    # ``**bold**`` first (greedy) so it doesn't get eaten by the ``*`` rule.
    if patched.count("**") % 2 == 1:
        patched = patched + "**"
    # Single ``*emph*`` — count *only* asterisks not part of ``**``.
    single_stars = patched.replace("**", "").count("*")
    if single_stars % 2 == 1:
        patched = patched + "*"
    # Inline code ``` `code` ``` — single backtick, ignoring triple-fence.
    if "```" not in patched and patched.count("`") % 2 == 1:
        patched = patched + "`"
    last_out = patched + trailing
    return f"{head}{sep}{last_out}" if sep else last_out


# Suffixes that look like the START of a block-level marker but haven't
# arrived in their proper context yet. Trim them from the streamed render
# so they don't appear as literal text mid-paragraph.
#
# Example: a chunk arrives ending with "More text. ##" — Markdown parses
# this as literal "##" (heading markers are only valid at line start). On
# the next delta, "## " becomes "## Section\n" which IS a valid heading.
# We hide the partial "##" until the line completes.
_BLOCK_MARKER_SUFFIXES = (
    "######",
    "#####",
    "####",
    "###",
    "##",
    "#",
    "```",
    "``",
    "`",
    "**",
    "*",
    "- ",
    "-",
    "> ",
    ">",
    "1. ",
    "2. ",
    "3. ",
    "4. ",
    "5. ",
    "1.",
    "2.",
    "3.",
    "4.",
    "5.",
)


def _trim_trailing_partial_marker(text: str) -> tuple[str, str]:
    """Return (safe_to_render, hidden_suffix).

    If the buffer ends with what *looks like* the start of a block-level
    Markdown marker that isn't yet usable, trim that suffix so it doesn't
    render as literal text mid-paragraph.

    Only triggers when the marker is **mid-line** (preceded by non-marker
    text). A line that *starts* with the marker is a legitimate
    in-progress block (heading, list item, etc.) and we let it through.
    """
    if not text:
        return text, ""
    head, sep, last_line = text.rpartition("\n")
    if not last_line:
        return text, ""
    for suffix in _BLOCK_MARKER_SUFFIXES:
        if not last_line.endswith(suffix):
            continue
        before = last_line[: -len(suffix)]
        # Only trim if the marker appears mid-line (text exists before it,
        # other than whitespace). A line like "## Sect" → before="" → don't
        # trim (it's a real heading in progress).
        if before.strip():
            visible = before.rstrip()
            return (
                f"{head}{sep}{visible}" if sep else visible,
                suffix,
            )
        return text, ""
    return text, ""


# Mirrors v1's tui.py:233 — kept here so we don't import from app/tui.py.
STEERING_TEMPLATE = """<steering>
{{ content }}
</steering>

<system-reminder>
The user has provided additional guidance during task execution.
Review the <steering> content carefully, consider how it affects your current approach,
and adjust your work accordingly while continuing toward the goal.
</system-reminder>"""


# ---------------------------------------------------------------------------
# Block sink — what ConsoleSession writes to
# ---------------------------------------------------------------------------


@dataclass
class _SubagentLive:
    """Per-subagent live state shown as a single transient transcript block.

    Renders as: ``⏺ subagent · explorer · running · 3 tools · last: Bash``
    """

    agent_id: str
    name: str
    prompt: str = ""
    tool_count: int = 0
    last_tool: str = ""

    def render(self, width: int, *, frame: int = 0) -> RenderableType:
        out = Text()
        out.append(
            f"{SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]} ",
            style="console.tool.spinner",
        )
        out.append("subagent", style="console.tool.name")
        out.append(" · ", style="console.tool.duration")
        out.append(self.name, style="console.tool.arg")
        out.append(" · ", style="console.tool.duration")
        out.append("running", style="console.tool.duration")
        if self.tool_count:
            out.append(f" · {self.tool_count} tools", style="console.tool.duration")
        if self.last_tool:
            out.append(f" · {self.last_tool}", style="console.tool.duration")
        return out


@dataclass
class _HistoryEntry:
    """One committed RichLog region plus metadata for search/navigation."""

    kind: str
    text: str
    line_start: int
    line_end: int
    label: str = ""
    block: Any | None = None
    renderable: RenderableType | None = None


class TextualSink:
    """Translate BlockSink calls into RichLog transcript writes.

    RichLog is the primary surface. Streaming model text, thinking, running
    tools, and running subagents all accumulate IN PLACE here: each update
    replaces the strips of the current transient block rather than appending
    a new line per delta or materialising in a separate region above the
    input.

    The "auto-scroll while idle, pause-on-user-scroll" behavior lives in
    a small ``_write`` helper that respects the log's current scroll
    position before emitting.
    """

    STREAM_BATCH_DELAY: float = 0.01
    STREAM_BATCH_MAX_CHARS: int = 256

    def __init__(
        self,
        log: RichLog,
        live: LivePane,
        *,
        max_log_lines: int = 0,
    ) -> None:
        self._log = log
        self._live = live
        self._max_log_lines = max(0, int(max_log_lines or 0))
        self._render_console = self._build_render_console(max(40, log.size.width or 100))
        # ----- streaming-text state -----
        # Raw accumulated text since the current streaming block began.
        # Empty string means no streaming block is open.
        self._stream_buffer: str = ""
        self._stream_pending_chars: int = 0
        self._stream_flush_timer: Any = None
        # Total number of strips currently occupied by the live Markdown
        # render of ``_stream_buffer`` in the RichLog. Tracked so each new
        # delta can pop them and write a fresh full render — that way the
        # user sees rendered Markdown (not raw ``**bold**`` markers) while
        # the response streams in.
        self._stream_strip_count: int = 0
        # ----------------------------------
        self._current_thinking: ThinkingBlock | None = None
        self._thinking_strip_count: int = 0
        self._tools: dict[str, ToolCallBlock] = {}
        self._tool_history: list[ToolCallBlock] = []
        self._detail_history: list[Any] = []
        self._history_entries: list[_HistoryEntry] = []
        # Active (collapsed) subagents. agent_id -> _SubagentLive
        self._subagent_states: dict[str, _SubagentLive] = {}
        self._active_operations_strip_count: int = 0
        self._active_operations_timer: Any = None
        self._active_operations_frame: int = 0
        # Set by the app: callback invoked on each commit so the app can
        # update the "pending lines while scrolled up" indicator.
        self._on_history_grew: Any = None
        # Set by the app: callback invoked with each committed history entry
        # so local transcript persistence can run outside the rendering path.
        self._on_entry_committed: Any = None
        # Set by the app: callback ``(state, detail)`` invoked when the
        # active phase changes (idle/thinking/tool/text) so a StatusBar
        # widget can surface progress + spinner.
        self._on_status_change: Any = None
        # Set by the app: callback ``(total_tokens, context_window_size)`` invoked
        # when the SDK reports context usage. Unknown usage is represented by
        # missing events, so this callback is only called for real measurements.
        self._on_context_update: Any = None

    def _emit_status(self, state: str, detail: str = "") -> None:
        if callable(self._on_status_change):
            self._on_status_change(state, detail)

    def handle_context_update(self, total_tokens: int, context_window_size: int) -> None:
        if callable(self._on_context_update):
            self._on_context_update(total_tokens, context_window_size)

    def _refresh_status_display(self) -> None:
        """Compute the active phase and emit it to the StatusBar.

        Priority: subagent > tool (running) > thinking > text > idle.
        Multiple tools in flight collapse to "Tool · N running".
        """
        if self._subagent_states:
            if len(self._subagent_states) == 1:
                state = next(iter(self._subagent_states.values()))
                detail = f"subagent · {state.name}"
                if state.last_tool:
                    detail = f"{detail} · {state.last_tool}"
                self._emit_status("tool", detail)
            else:
                self._emit_status("tool", f"{len(self._subagent_states)} subagents")
            return
        if self._tools:
            if len(self._tools) == 1:
                tc = next(iter(self._tools.values()))
                detail = tc.name
                # Add an inline arg snippet if available
                from yaacli.console.blocks.tool_call import summarize_args

                arg_str = summarize_args(tc.name, tc.args)
                if arg_str:
                    detail = f"{tc.name} · {arg_str[:40]}"
                self._emit_status("tool", detail)
            else:
                self._emit_status("tool", f"{len(self._tools)} tools running")
            return
        if self._current_thinking is not None:
            self._emit_status("thinking", "")
            return
        if self._stream_buffer:
            self._emit_status("text", "")
            return
        self._emit_status("idle", "")

    @property
    def width(self) -> int:
        # RichLog's vertical scrollbar occupies the right-most content
        # column when history overflows. Render one column narrower so long
        # Markdown/thinking lines don't sit underneath the scrollbar.
        return max(40, (self._log.size.width or 80) - 1)

    def _build_render_console(self, width: int) -> RichConsole:
        return RichConsole(
            theme=build_theme(),
            force_terminal=True,
            color_system="truecolor",
            width=width,
            height=max(1, self._log.size.height or 25),
        )

    def _resync_width(self) -> None:
        if self._render_console.width != self.width:
            self._render_console = self._build_render_console(self.width)

    def _pop_strips(self, count: int) -> None:
        """Remove the last ``count`` strips from the RichLog.

        ``RichLog.write`` calls ``refresh`` internally, but mutating
        ``log.lines`` directly does NOT — the widget will only repaint the
        region that was newly written. When we pop+rewrite a region the
        space above the new write goes stale unless we explicitly refresh.
        """
        popped = False
        for _ in range(count):
            if self._log.lines:
                self._log.lines.pop()
                popped = True
        if popped:
            self._invalidate_log_line_cache()

    def _invalidate_log_line_cache(self) -> None:
        """Clear RichLog's private render cache after direct line mutation."""
        import contextlib

        with contextlib.suppress(Exception):
            line_cache = getattr(self._log, "_line_cache", None)
            if line_cache is not None:
                line_cache.clear()

    def _refresh_log(self) -> None:
        """Force a full repaint AND relayout of the RichLog.

        Required after pop+write cycles so the streaming Markdown re-renders
        even when focus is on the input. ``refresh()`` alone marks the
        widget dirty. We also clear RichLog's private line cache when
        direct line mutation has happened, so the new strips are pulled
        from ``self._log.lines`` without needing a focus/style change.
        """
        import contextlib

        with contextlib.suppress(Exception):
            self._log.refresh(layout=True)

    def _commit(
        self,
        renderable: RenderableType,
        *,
        kind: str = "system",
        search_text: str = "",
        label: str = "",
        block: Any | None = None,
    ) -> None:
        """Render through themed Console and push to the RichLog."""
        self._pop_active_operations_render()
        self._resync_width()
        before = len(self._log.lines)
        segments = list(self._render_console.render(renderable))
        self._log.write(Segments(segments), width=self.width)
        after = len(self._log.lines)
        entry = _HistoryEntry(
            kind=kind,
            text=search_text,
            label=label,
            line_start=before,
            line_end=after,
            block=block,
            renderable=renderable if block is None else None,
        )
        self._history_entries.append(entry)
        self._trim_history_lines()
        if callable(self._on_entry_committed):
            self._on_entry_committed(entry)
        if callable(self._on_history_grew):
            self._on_history_grew()
        if self._has_active_operations():
            self._render_active_operations(notify_history=False)

    def _trim_history_lines(self) -> None:
        if self._max_log_lines <= 0:
            return
        overflow = len(self._log.lines) - self._max_log_lines
        if overflow <= 0:
            return
        del self._log.lines[:overflow]
        self._invalidate_log_line_cache()
        adjusted: list[_HistoryEntry] = []
        for entry in self._history_entries:
            if entry.line_end <= overflow:
                continue
            entry.line_start = max(0, entry.line_start - overflow)
            entry.line_end = max(entry.line_start, entry.line_end - overflow)
            adjusted.append(entry)
        self._history_entries = adjusted
        try:
            self._log.scroll_to(
                y=max(0, self._log.scroll_y - overflow),
                animate=False,
                immediate=True,
            )
        except Exception:
            logger.debug("Could not adjust log scroll after trim", exc_info=True)

    def _write_strips_counted(self, renderable: RenderableType) -> int:
        """Render + write a renderable; return the number of strips it occupied."""
        self._resync_width()
        before = len(self._log.lines)
        self._log.write(
            Segments(list(self._render_console.render(renderable))),
            width=self.width,
        )
        return max(0, len(self._log.lines) - before)

    def _render_streaming_buffer(self) -> None:
        """Render the current streaming text snapshot into the RichLog."""
        safe_text, _hidden = _trim_trailing_partial_marker(self._stream_buffer)
        renderable_text = _close_open_markdown_markers(safe_text)
        block = ModelTextBlock()
        block.append(renderable_text)
        self._stream_strip_count = self._write_strips_counted(block.render(self.width))
        self._refresh_log()

    def _replace_streaming_render(self) -> None:
        self._pop_strips(self._stream_strip_count)
        self._stream_strip_count = 0
        self._render_streaming_buffer()
        self._stream_pending_chars = 0

    def _cancel_stream_flush_timer(self) -> None:
        timer = self._stream_flush_timer
        self._stream_flush_timer = None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                logger.debug("Could not stop stream flush timer", exc_info=True)

    def _schedule_stream_flush(self) -> None:
        if self._stream_flush_timer is not None:
            return
        try:
            self._stream_flush_timer = self._log.set_timer(
                self.STREAM_BATCH_DELAY,
                self._flush_streaming_render_timer,
            )
        except Exception:
            self._flush_streaming_render_timer()

    def _flush_streaming_render_timer(self) -> None:
        self._stream_flush_timer = None
        if not self._stream_buffer or self._stream_pending_chars <= 0:
            return
        self._replace_streaming_render()
        if callable(self._on_history_grew):
            self._on_history_grew()

    def reflow_streaming_text(self) -> None:
        """Re-render any in-flight RichLog stream after terminal resize."""
        did_reflow = False
        self._cancel_stream_flush_timer()
        if self._stream_buffer:
            self._replace_streaming_render()
            did_reflow = True
        if self._current_thinking is not None:
            self._replace_thinking_render()
            did_reflow = True
        if not did_reflow:
            self._resync_width()

    def _render_thinking_buffer(self) -> None:
        if self._current_thinking is None:
            self._thinking_strip_count = 0
            return
        self._thinking_strip_count = self._write_strips_counted(self._current_thinking.render(self.width))
        self._refresh_log()

    def _replace_thinking_render(self) -> None:
        self._pop_strips(self._thinking_strip_count)
        self._thinking_strip_count = 0
        self._render_thinking_buffer()

    def _has_active_operations(self) -> bool:
        return bool(self._tools or self._subagent_states)

    def _active_operation_renderables(self) -> list[RenderableType]:
        renderables: list[RenderableType] = []
        renderables.extend(
            block.render(self.width, frame=self._active_operations_frame) for block in self._tools.values()
        )
        renderables.extend(
            state.render(self.width, frame=self._active_operations_frame) for state in self._subagent_states.values()
        )
        return renderables

    def _ensure_active_operations_timer(self) -> None:
        if self._active_operations_timer is not None:
            return
        try:
            self._active_operations_timer = self._log.set_interval(
                0.1,
                self._tick_active_operations,
            )
        except Exception:
            self._active_operations_timer = None

    def _stop_active_operations_timer(self) -> None:
        timer = self._active_operations_timer
        self._active_operations_timer = None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                logger.debug("Could not stop active operation timer", exc_info=True)

    def _tick_active_operations(self) -> None:
        if not self._has_active_operations():
            self._stop_active_operations_timer()
            return
        self._active_operations_frame = (self._active_operations_frame + 1) % len(SPINNER_FRAMES)
        self._replace_active_operations_render(notify_history=False)

    def _pop_active_operations_render(self) -> bool:
        if self._active_operations_strip_count <= 0:
            return False
        self._pop_strips(self._active_operations_strip_count)
        self._active_operations_strip_count = 0
        return True

    def _render_active_operations(self, *, notify_history: bool) -> None:
        renderables = self._active_operation_renderables()
        if not renderables:
            self._active_operations_strip_count = 0
            self._stop_active_operations_timer()
            return
        self._active_operations_strip_count = self._write_strips_counted(Group(*renderables))
        self._refresh_log()
        self._ensure_active_operations_timer()
        if notify_history and callable(self._on_history_grew):
            self._on_history_grew()

    def _replace_active_operations_render(self, *, notify_history: bool) -> None:
        self._pop_active_operations_render()
        self._render_active_operations(notify_history=notify_history)

    def clear_active_operations(self) -> None:
        self._pop_active_operations_render()
        self._tools.clear()
        self._subagent_states.clear()
        self._active_operations_frame = 0
        self._stop_active_operations_timer()
        self._live.clear_all()
        self._refresh_log()
        self._refresh_status_display()

    # ------- BlockSink protocol -------

    def show_breadcrumb(self, text: str) -> None:
        # If a streaming text block is in progress, finalise it first so the
        # breadcrumb doesn't land in the middle of a sentence.
        self._flush_streaming_text()
        self._commit(
            Text(text, style="dim italic"),
            kind="system",
            search_text=text,
            label=text[:80],
        )

    def handle_text_delta(self, delta: str) -> None:
        """Live Markdown streaming: each delta repaints the full buffer.

        Strategy:
          1. Append delta to buffer.
          2. Pop the strips of the previous render.
          3. Render the buffer (with synthetic closers for unfinished
             inline markers — see ``_close_open_markdown_markers``) so the
             user never sees raw ``**``/``` ` ``` while streaming.
          4. Write the resulting strips, track the count for next pop.
          5. Force a full ``log.refresh()`` so the widget repaints regardless
             of which widget currently has focus.
        """
        if not delta:
            return

        first_delta = not self._stream_buffer
        self._stream_buffer += delta
        self._stream_pending_chars += len(delta)

        # Render through Markdown — patching unfinished inline markers so
        # the user doesn't see raw ``**`` / ``` ` ``` mid-stream. Also trim
        # any trailing block-marker suffix (``... text. ##``) that would
        # otherwise render as literal text — Markdown only treats those as
        # block markers at line-start, not mid-line.
        should_flush = first_delta or self._stream_pending_chars >= self.STREAM_BATCH_MAX_CHARS or "\n" in delta
        if should_flush:
            self._cancel_stream_flush_timer()
            self._replace_streaming_render()
            if callable(self._on_history_grew):
                self._on_history_grew()
        else:
            self._schedule_stream_flush()

        if first_delta:
            self._refresh_status_display()

    def end_text(self) -> None:
        self._flush_streaming_text()

    def _flush_streaming_text(self) -> None:
        """Finalise the in-progress streaming text block.

        On end_text, redraw once with the *real* (unpatched) buffer so any
        legitimately-unclosed marker (rare) gets handled by rich.markdown
        the way it normally would. Then reset state.
        """
        if not self._stream_buffer:
            self._stream_strip_count = 0
            self._stream_pending_chars = 0
            return

        # Pop our synthetic-closer render and emit a final un-patched one.
        self._cancel_stream_flush_timer()
        self._pop_strips(self._stream_strip_count)
        block = ModelTextBlock()
        block.append(self._stream_buffer)
        self._commit(
            block.render(self.width),
            kind="assistant",
            search_text=self._stream_buffer,
            label="assistant",
            block=block,
        )
        self._refresh_log()
        self._stream_buffer = ""
        self._stream_strip_count = 0
        self._stream_pending_chars = 0
        self._refresh_status_display()

    def handle_thinking_delta(self, delta: str) -> None:
        first = self._current_thinking is None
        if self._current_thinking is None:
            self._current_thinking = ThinkingBlock()
        self._current_thinking.append(delta)
        self._replace_thinking_render()
        if callable(self._on_history_grew):
            self._on_history_grew()
        if first:
            self._refresh_status_display()

    def end_thinking(self) -> None:
        if self._current_thinking is None:
            return
        block = self._current_thinking
        self._current_thinking = None
        self._pop_strips(self._thinking_strip_count)
        self._thinking_strip_count = 0
        if block.text:
            self._commit(
                block.render(self.width),
                kind="thinking",
                search_text=block.text,
                label="thinking",
                block=block,
            )
        self._refresh_status_display()

    def handle_tool_call_start(self, tool_call_id: str, name: str, args: Any = None) -> None:
        self._flush_streaming_text()
        self.end_thinking()
        block = self._tools.get(tool_call_id)
        if block is not None:
            block.name = name or block.name
            block.update_args(args)
            self._replace_active_operations_render(notify_history=False)
            self._refresh_status_display()
            return
        block = ToolCallBlock(name=name, args=args)
        self._tools[tool_call_id] = block
        if self._active_operations_strip_count == 0:
            self._active_operations_frame = 0
        self._replace_active_operations_render(notify_history=True)
        self._refresh_status_display()

    def handle_tool_call_complete(self, tool_call_id: str, result: Any, *, error: bool = False) -> None:
        self._pop_active_operations_render()
        block = self._tools.pop(tool_call_id, None)
        if block is None:
            block = ToolCallBlock(name="(unknown)", args=None)
        block.complete(result, error=error)
        # Commit the final tool block to history. If a streaming text block
        # is in progress, flush it first so the tool block appears after the
        # text, not inside it.
        self._flush_streaming_text()
        self._tool_history.append(block)
        self._detail_history.append(block)
        self._commit(
            block.render(self.width),
            kind="tool",
            search_text=self._tool_search_text(block),
            label=block.name,
            block=block,
        )
        self._refresh_status_display()

    # ------- subagent (collapsed) -------

    def handle_subagent_start(self, agent_id: str, name: str, prompt_preview: str = "") -> None:
        """Pin a single live block for the subagent. All tool calls under it
        will only update the running counter on this block — they don't
        appear as top-level blocks in the log."""
        state = _SubagentLive(agent_id=agent_id, name=name, prompt=prompt_preview)
        self._subagent_states[agent_id] = state
        if self._active_operations_strip_count == 0:
            self._active_operations_frame = 0
        self._replace_active_operations_render(notify_history=True)
        self._refresh_status_display()

    def handle_subagent_progress(self, agent_id: str, tool_name: str, tool_count: int) -> None:
        state = self._subagent_states.get(agent_id)
        if state is None:
            return
        state.last_tool = tool_name
        state.tool_count = tool_count
        self._replace_active_operations_render(notify_history=False)
        self._refresh_status_display()

    def handle_subagent_complete(
        self,
        agent_id: str,
        *,
        success: bool = True,
        result_preview: str = "",
        duration_seconds: float = 0.0,
    ) -> None:
        self._pop_active_operations_render()
        state = self._subagent_states.pop(agent_id, None)
        if state is None:
            return
        # Commit a summary line to history.
        self._flush_streaming_text()
        summary = Text()
        summary.append(f"{GLYPHS.DOT} ", style="console.dot.success" if success else "console.dot.error")
        summary.append("subagent ", style="console.tool.name")
        summary.append(state.name, style="console.tool.arg")
        summary.append(" · ", style="console.tool.duration")
        summary.append(
            f"{state.tool_count} tools · {duration_seconds:.1f}s",
            style="console.tool.result",
        )
        if not success:
            summary.append(" · failed", style="console.dot.error")
        self._commit(
            summary,
            kind="tool",
            search_text=f"subagent {state.name} {result_preview}",
            label=f"subagent {state.name}",
        )
        self._refresh_status_display()

    # ------- block-sink helpers -------

    def write(self, renderable: RenderableType) -> None:
        """Write a pre-rendered Rich renderable straight to the log history."""
        self._flush_streaming_text()
        self._commit(renderable, search_text=str(renderable), label=str(renderable)[:80])

    def write_block(self, block: Any) -> None:
        self._flush_streaming_text()
        kind, label, search_text = self._metadata_for_block(block)
        if isinstance(block, ToolCallBlock):
            self._tool_history.append(block)
            self._detail_history.append(block)
        elif isinstance(block, EditBlock):
            self._detail_history.append(block)
        self._commit(
            block.render(self.width),
            kind=kind,
            search_text=search_text,
            label=label,
            block=block,
        )

    def _metadata_for_block(self, block: Any) -> tuple[str, str, str]:
        if isinstance(block, ToolCallBlock):
            return ("tool", block.name, self._tool_search_text(block))
        if isinstance(block, ErrorBlock):
            text = "\n".join(part for part in (block.title, block.body, block.detail) if part)
            return ("error", block.title, text)
        if isinstance(block, UserPromptBlock):
            text = getattr(block, "text", "")
            return ("user", "user", text)
        if isinstance(block, ModelTextBlock):
            text = getattr(block, "text", "")
            return ("assistant", "assistant", text)
        if isinstance(block, ThinkingBlock):
            text = getattr(block, "text", "")
            return ("thinking", "thinking", text)
        if isinstance(block, EditBlock):
            text = f"{block.path}\n{block.edits!r}"
            return ("tool", f"edit {block.path}", text)
        if isinstance(block, SystemBlock):
            title = getattr(block, "title", "system")
            return ("system", str(title), str(block))
        return ("system", type(block).__name__, str(block))

    def _tool_search_text(self, block: ToolCallBlock) -> str:
        parts = [
            block.name,
            block.command_text(),
            block.output_text(),
            json.dumps(block.args, ensure_ascii=False, default=str),
        ]
        return "\n".join(part for part in parts if part)

    def search_entries(self, query: str) -> list[int]:
        needle = query.casefold().strip()
        if not needle:
            return []
        return [
            i
            for i, entry in enumerate(self._history_entries)
            if needle in f"{entry.kind}\n{entry.label}\n{entry.text}".casefold()
        ]

    def history_entry_count(self) -> int:
        return len(self._history_entries)

    def scroll_to_entry(self, entry_index: int) -> bool:
        if entry_index < 0 or entry_index >= len(self._history_entries):
            return False
        entry = self._history_entries[entry_index]
        self._log.scroll_to(y=max(0, entry.line_start), animate=False, immediate=True)
        return True

    def jump_to_marker(self, kind: str, direction: int, current_y: float) -> bool:
        target = self.marker_entry_index(kind, direction, current_y)
        if target is None:
            return False
        return self.scroll_to_entry(target)

    def marker_entry_index(
        self,
        kind: str,
        direction: int,
        current_y: float,
        *,
        skip_entry_index: int | None = None,
    ) -> int | None:
        entries = [
            (i, entry)
            for i, entry in enumerate(self._history_entries)
            if i != skip_entry_index
            and not (kind == "user" and entry.text.lstrip().startswith("/"))
            and (
                entry.kind == kind or (kind == "error" and isinstance(entry.block, ToolCallBlock) and entry.block.error)
            )
        ]
        if not entries:
            return None
        if direction < 0:
            before = [(i, e) for i, e in entries if e.line_start < current_y - 0.5]
            target = before[-1] if before else entries[-1]
        else:
            after = [(i, e) for i, e in entries if e.line_start > current_y + 0.5]
            target = after[0] if after else entries[0]
        return target[0]

    def last_tool(self) -> ToolCallBlock | None:
        return self._tool_history[-1] if self._tool_history else None

    def toggle_last_tool_details(self) -> bool:
        block = self._detail_history[-1] if self._detail_history else None
        if block is None or not hasattr(block, "toggle_expanded"):
            return False
        block.toggle_expanded()
        self._rebuild_history()
        return True

    def expand_all_tools(self) -> bool:
        changed = False
        for block in self._detail_history:
            if hasattr(block, "expanded") and not block.expanded:
                block.expanded = True
                changed = True
        if changed:
            self._rebuild_history()
        return changed

    def detail_blocks(self) -> list[Any]:
        return list(self._detail_history)

    def _rebuild_history(self) -> None:
        entries = list(self._history_entries)
        self._log.clear()
        for entry in entries:
            entry.line_start = len(self._log.lines)
            renderable = entry.block.render(self.width) if entry.block is not None else entry.renderable
            if renderable is None:
                renderable = Text(entry.text)
            self._resync_width()
            self._log.write(
                Segments(list(self._render_console.render(renderable))),
                width=self.width,
            )
            entry.line_end = len(self._log.lines)
        self._history_entries = entries
        self._invalidate_log_line_cache()
        self._refresh_log()

    def clear_history_metadata(self) -> None:
        self._history_entries.clear()
        self._tool_history.clear()
        self._detail_history.clear()


# ---------------------------------------------------------------------------
# HITL modal
# ---------------------------------------------------------------------------


class HitlModal(ModalScreen[tuple[str, str | None]]):
    """Modal screen for tool approvals. Returns (decision, reason|None)."""

    DEFAULT_CSS = """
    HitlModal {
        align: center middle;
    }
    HitlModal > Vertical {
        width: 80;
        height: auto;
        max-height: 20;
        border: thick $warning;
        padding: 1 2;
        background: $surface;
    }
    HitlModal Static {
        margin-bottom: 1;
    }
    HitlModal #buttons {
        height: 3;
        align: center middle;
    }
    HitlModal Button {
        margin: 0 1;
    }
    """

    BINDINGS: ClassVar = [
        Binding("y", "approve_once", "Approve once"),
        Binding("a", "approve_all", "Approve all"),
        Binding("n", "reject", "Reject"),
        Binding("escape", "reject", "Reject"),
    ]

    def __init__(self, tool_name: str, args_summary: str) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._args_summary = args_summary

    def compose(self) -> ComposeResult:
        title = Text()
        title.append(f"{GLYPHS.WARNING} ", style="bold yellow")
        title.append(self._tool_name, style="bold")
        title.append(" needs approval", style="bold yellow")

        body = Text(self._args_summary, style="white", overflow="fold")

        with Vertical():
            yield Static(title)
            yield Static(body)
            yield Static(Text("[y] approve once  [a] approve all  [n] reject", style="dim"))
            yield Vertical(
                Button("Approve (y)", id="yes", variant="success"),
                Button("All (a)", id="all", variant="warning"),
                Button("Reject (n)", id="no", variant="error"),
                id="buttons",
            )

    def action_approve_once(self) -> None:
        self.dismiss(("approve_once", None))

    def action_approve_all(self) -> None:
        self.dismiss(("approve_all", None))

    def action_reject(self) -> None:
        self.dismiss(("reject", "User rejected"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.action_approve_once()
        elif event.button.id == "all":
            self.action_approve_all()
        elif event.button.id == "no":
            self.action_reject()


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


class YaacliTextualApp(App[None]):
    """Top-level Textual app.

    Constructed with a fully-initialised runtime; lifecycle (browser, MCP,
    runtime) is owned by the launcher (``run_textual_tui``) so we can use
    AsyncExitStack the same way the v1 TUIApp does.
    """

    # Pick a modern theme registered by Textual; the user can override.
    THEME_NAME: ClassVar[str] = "tokyo-night"

    CSS = """
    Screen {
        background: #11131a;
    }
    #log, #tool_details {
        height: 1fr;
        border: none;
        padding: 1 2;
        background: #11131a;
        color: #d8dee9;
        overflow-x: hidden;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
    }
    #input_chrome {
        dock: bottom;
        height: auto;
    }
    #input_chrome > StatusBar,
    #input_chrome > PromptArea,
    #input_chrome > FooterHint {
        dock: none;
    }
    """

    BINDINGS: ClassVar = [
        Binding("ctrl+c", "interrupt", "Cancel/Exit", priority=True, show=False),
        Binding("ctrl+d", "quit", "Exit", priority=True, show=False),
        Binding("end", "scroll_to_bottom", "Scroll to bottom", show=False),
        Binding("pageup", "page_up", "Page up", show=False),
        Binding("pagedown", "page_down", "Page down", show=False),
        Binding("ctrl+f", "search_prompt", "Search output", show=False),
        Binding("f3", "search_next", "Next search match", show=False),
        Binding("shift+f3", "search_previous", "Previous search match", show=False),
        Binding("alt+u", "jump_previous_user", "Previous user", show=False),
        Binding("alt+a", "jump_previous_assistant", "Previous assistant", show=False),
        Binding("alt+t", "jump_previous_tool", "Previous tool", show=False),
        Binding("alt+e", "jump_next_error", "Next error", show=False),
        Binding("ctrl+o", "tool_toggle_details", "Toggle tool details", show=False),
        Binding("ctrl+shift+o", "tool_expand_all", "Expand all tools", show=False),
        Binding("ctrl+alt+c", "tool_copy_command", "Copy tool command", show=False),
        Binding("ctrl+alt+v", "tool_copy_output", "Copy tool output", show=False),
        Binding("ctrl+r", "tool_rerun", "Rerun last tool", show=False),
    ]

    def __init__(
        self,
        *,
        config: YaacliConfig,
        config_manager: ConfigManager | None = None,
        runtime: Any,
        cwd: Path,
        model_name: str | None,
        active_model_name: str | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._config_manager = config_manager
        self._runtime = runtime
        self._cwd = cwd
        self._model_name = model_name or "(unset)"
        self._active_model_name = self._resolve_initial_active_model_name(active_model_name)
        self._session_id = new_session_id()
        self._transcript: TranscriptStore | None = self._build_transcript_store()
        self._restoring_transcript = False
        self._turn_started_at: float = 0.0
        self._turn_tool_count: int = 0
        self._turn_error_count: int = 0
        self._current_context_tokens: int = 0
        self._context_window_size: int = 0
        self._mode = "ACT"
        self._message_history: list[Any] = []
        self._approval_session_grants: set[str] = set()
        self._agent_task: asyncio.Task[None] | None = None
        self._ctrl_c_at: float = 0.0
        self._prompt_history: list[str] = []
        self._history_index: int | None = None
        self._history_draft: str = ""
        self._recent_command_names: list[str] = []
        self._search_query: str = ""
        self._search_matches: list[int] = []
        self._search_match_index: int = -1
        self._tool_details_active: bool = False

        # Widgets — composed in compose()
        self._header = HeaderBar()
        self._log = StreamingRichLog(
            id="log",
            min_width=1,
            wrap=True,
            markup=False,
            auto_scroll=True,
            highlight=False,
        )
        self._tool_details = RichLog(
            id="tool_details",
            min_width=1,
            wrap=True,
            markup=False,
            auto_scroll=False,
            highlight=False,
        )
        self._tool_details.display = False
        self._live = LivePane()
        self._steering = SteeringList()
        self._slash_menu = SlashMenu()
        self._mention_menu = PathMentionMenu()
        self._input = PromptArea()
        self._footer = FooterHint()
        self._status = StatusBar()
        self._scroll_indicator = ScrollIndicator()
        self._sink = TextualSink(
            self._log,
            self._live,
            max_log_lines=getattr(getattr(config, "display", None), "max_output_lines", 0),
        )
        self._log.on_width_changed = self._sink.reflow_streaming_text
        # Wire the auto-scroll watchdog: each time history grows, decide
        # whether to follow it or to bump the "↓ N new lines" indicator.
        self._sink._on_history_grew = self._on_history_grew
        # Wire status updates from the sink so tool/text/thinking activity
        # surfaces in the StatusBar above the input.
        self._sink._on_status_change = self._on_sink_status_change
        self._sink._on_context_update = self._on_context_update
        self._sink._on_entry_committed = self._on_history_entry_committed
        self._user_scrolled_up: bool = False
        self._pending_lines_while_scrolled: int = 0

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def has_session_data(self) -> bool:
        return self._transcript.has_data() if self._transcript is not None else False

    def _session_config_value(self, name: str, default: Any) -> Any:
        session_config = getattr(self._config, "session", None)
        return getattr(session_config, name, default)

    def _session_auto_save_enabled(self) -> bool:
        return bool(self._session_config_value("auto_save_history", True))

    def _build_transcript_store(self) -> TranscriptStore | None:
        if self._config_manager is None:
            return None
        raw_dir = str(self._session_config_value("session_dir", "") or "")
        sessions_dir = Path(raw_dir).expanduser() if raw_dir else self._config_manager.get_sessions_dir()
        store = TranscriptStore(
            sessions_dir=sessions_dir,
            session_id=self._session_id,
            working_dir=self._cwd,
            model=self._model_name,
            max_sessions=int(self._session_config_value("max_sessions", 100) or 100),
        )
        if self._session_auto_save_enabled():
            store.start()
        return store

    # ---------------- compose / mount ----------------

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._log
        yield self._tool_details
        yield self._scroll_indicator
        yield self._mention_menu
        yield self._slash_menu
        yield self._steering
        yield self._live
        with Vertical(id="input_chrome"):
            yield self._status
            yield self._input
            yield self._footer

    def on_mount(self) -> None:
        # Apply chosen theme. Available themes were registered by Textual core.
        try:
            self.theme = self.THEME_NAME
        except Exception:
            logger.debug("Could not set theme %s", self.THEME_NAME, exc_info=True)
        # Allow text selection in the log so users can drag-select.
        self._log.can_focus = True
        self._tool_details.can_focus = True
        # Watch the log's scroll position so we can detect manual scroll.
        self.watch(self._log, "scroll_y", self._on_log_scroll_y_changed, init=False)
        # Wire slash menu: feed it the registered commands. The menu is then
        # updated on every TextArea.Changed event (see ``on_text_area_changed``).
        from yaacli.console.palette import DEFAULT_COMMANDS

        self._slash_menu.set_all_commands(tuple(DEFAULT_COMMANDS))
        self._slash_menu.set_subagent_provider(self._discover_subagents)
        self._slash_menu.set_recent_commands(tuple(self._recent_command_names))
        self._mention_menu.set_workspace_root(self._cwd)
        self._sync_completion_menu_offsets()
        self._refresh_header()
        self._footer.mode = self._mode
        self._footer.state = "ready"
        self._footer.model_label = self._short_model_label()
        self._input.focus()
        # Greeting breadcrumb
        self._sink.show_breadcrumb("Type / for commands. /exit to quit.")

    def on_text_area_changed(self, event: Any) -> None:
        """TextArea content changed — drive the slash menu visibility/filter."""
        # Only react to changes from our PromptArea, not e.g. a future
        # editor widget elsewhere.
        if event.text_area is self._input:
            self._input.normalize_terminal_input()
            self._sync_completion_menu_offsets()
            token = self._active_path_mention_token()
            if token is not None:
                self._slash_menu.update_query("")
                self._mention_menu.update_query(token[2])
            else:
                self._mention_menu.update_query("")
                self._slash_menu.update_query(self._input.text)

    def on_resize(self, _event: Any) -> None:
        self._sync_completion_menu_offsets()

    def _sync_completion_menu_offsets(self) -> None:
        prompt_height = getattr(self._input.region, "height", 0) or self._input.size.height or 0
        status_height = getattr(self._status.region, "height", 0) or self._status.size.height or 0
        footer_height = getattr(self._footer.region, "height", 0) or self._footer.size.height or 0
        chrome_height = max(3, prompt_height) + max(1, status_height) + max(1, footer_height)
        offset = (0, -chrome_height)
        self._mention_menu.styles.offset = offset
        self._slash_menu.styles.offset = offset

    def _on_log_scroll_y_changed(self, _new_value: float) -> None:
        """RichLog scroll position changed (programmatic OR user-driven)."""
        self._handle_log_scroll()

    # ---------------- input handling ----------------

    async def on_key(self, event: Any) -> None:
        """App-level key interceptor — handle completion menu navigation.

        When a completion menu is open, ↑/↓ navigate, Tab/Enter complete the
        selection, Escape closes the menu. We do this here (not as bindings)
        so we can short-circuit before the keys reach PromptArea.
        """
        if self._mention_menu.is_open:
            if event.key == "down":
                self._mention_menu.move_down()
                event.stop()
                event.prevent_default()
                return
            if event.key == "up":
                self._mention_menu.move_up()
                event.stop()
                event.prevent_default()
                return
            if event.key in {"tab", "right", "enter"}:
                self._complete_path_mention()
                event.stop()
                event.prevent_default()
                return
            if event.key == "escape":
                self._mention_menu.update_query("")
                event.stop()
                event.prevent_default()
                return

        active_mention = self._active_path_mention_token()
        if active_mention is not None and event.key in {"tab", "right", "enter"}:
            # Terminal input can deliver "@path<Tab>" before the Changed event
            # has repainted the menu. Refresh synchronously so fast completion
            # behaves the same as the slower visual path.
            self._mention_menu.update_query(active_mention[2])
            if self._mention_menu.selected_item is not None:
                self._complete_path_mention()
                event.stop()
                event.prevent_default()
                return

        if self._slash_menu.is_open:
            if event.key == "down":
                self._slash_menu.move_down()
                event.stop()
                event.prevent_default()
                return
            if event.key == "up":
                self._slash_menu.move_up()
                event.stop()
                event.prevent_default()
                return
            if event.key in {"tab", "right"}:
                cmd = self._slash_menu.selected_command
                if cmd is not None:
                    self._set_prompt_text(self._completion_text_for_command(cmd))
                event.stop()
                event.prevent_default()
                return
            if event.key == "enter":
                cmd = self._slash_menu.selected_command
                if cmd is not None:
                    completed = self._completion_text_for_command(cmd)
                    if self._command_has_required_params(cmd):
                        self._set_prompt_text(completed)
                    else:
                        self._set_prompt_text("")
                        await self._submit_prompt_text(completed.strip())
                event.stop()
                event.prevent_default()
                return
            if event.key == "escape":
                self._set_prompt_text("")
                event.stop()
                event.prevent_default()
                return

        if self.focused is self._input and event.key in {"up", "down"}:
            if self._scroll_log_for_empty_prompt(event.key):
                event.stop()
                event.prevent_default()
                return
            direction = -1 if event.key == "up" else 1
            if self._navigate_prompt_history(direction):
                event.stop()
                event.prevent_default()

    async def on_prompt_area_submitted(self, event: PromptArea.Submitted) -> None:
        # If the slash menu is open, complete to the selected command
        # rather than submitting the partial input.
        if self._slash_menu.is_open:
            cmd = self._slash_menu.selected_command
            if cmd is not None:
                completed = self._completion_text_for_command(cmd)
                if self._command_has_required_params(cmd):
                    self._set_prompt_text(completed)
                    return
                # Treat commands with no required params as the submission directly.
                event = PromptArea.Submitted(self._input, completed.strip())

        text = event.value.strip()
        if not text:
            return
        self._set_prompt_text("")
        await self._submit_prompt_text(text)

    async def _submit_prompt_text(self, text: str) -> None:
        self._record_prompt_history(text)
        agent_prompt = self._inject_mentioned_context(text)

        # Mid-run: route to steering
        if self._agent_task is not None and not self._agent_task.done():
            self._inject_steering(agent_prompt)
            return

        # Idle: slash command or new turn
        if text.startswith("/"):
            handled = await self._handle_command(text)
            if handled:
                return
            # fall through — unknown slash command becomes a regular prompt

        self._sink.write_block(UserPromptBlock(text=text))
        self._agent_task = asyncio.create_task(self._run_turn(agent_prompt))

    def _cursor_offset(self) -> int:
        location = getattr(self._input, "cursor_location", None)
        if location is None:
            return len(self._input.text)
        row = getattr(location, "row", None)
        col = getattr(location, "column", None)
        if row is None or col is None:
            try:
                row, col = int(location[0]), int(location[1])
            except Exception:
                return len(self._input.text)
        lines = self._input.text.splitlines(keepends=True)
        if not lines:
            return 0
        row = max(0, min(int(row), len(lines) - 1))
        col = max(0, int(col))
        return min(len(self._input.text), sum(len(line) for line in lines[:row]) + col)

    def _active_path_mention_token(self) -> tuple[int, int, str] | None:
        offset = self._cursor_offset()
        left = self._input.text[:offset]
        if not left:
            return None
        token_start = len(left)
        while token_start > 0 and not left[token_start - 1].isspace():
            token_start -= 1
        token = left[token_start:]
        if not token.startswith("@"):
            return None
        if any(ch.isspace() for ch in token):
            return None
        return token_start, offset, token

    def _complete_path_mention(self) -> None:
        item = self._mention_menu.selected_item
        token = self._active_path_mention_token()
        if item is None or token is None:
            return
        start, end, _token = token
        replacement = f"@{item.display}"
        if not item.is_dir:
            replacement += " "
        text = self._input.text
        self._set_prompt_text(f"{text[:start]}{replacement}{text[end:]}")
        self._mention_menu.update_query("")

    def _inject_mentioned_context(self, text: str) -> str:
        blocks: list[str] = []
        seen: set[str] = set()
        for raw_path in re.findall(r"(?<!\S)@([^@\s]+)", text):
            normalized = raw_path.rstrip(".,;:)")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            block = self._render_mention_context(normalized)
            if block:
                blocks.append(block)
        if not blocks:
            return text
        joined_blocks = "\n".join(blocks)
        return f"{text}\n\n<mentioned-context>\n{joined_blocks}\n</mentioned-context>"

    def _render_mention_context(self, path_text: str) -> str:
        if path_text.startswith(("/", "~")) or ".." in Path(path_text).parts:
            return ""
        target = (self._cwd / path_text).resolve()
        try:
            target.relative_to(self._cwd.resolve())
        except ValueError:
            return ""
        if not target.exists():
            return ""
        if target.is_dir():
            entries: list[str] = []
            for child in sorted(target.rglob("*")):
                if any(part in {".git", ".venv", "node_modules", "__pycache__"} for part in child.parts):
                    continue
                try:
                    rel = child.relative_to(self._cwd).as_posix()
                except ValueError:
                    continue
                entries.append(f"{rel}/" if child.is_dir() else rel)
                if len(entries) >= 120:
                    entries.append("... truncated ...")
                    break
            body = "\n".join(entries) if entries else "(empty directory)"
            return (
                f'<mentioned-directory path="{self._xml_escape(path_text)}">\n'
                f"{self._xml_escape(body)}\n"
                "</mentioned-directory>"
            )
        if not target.is_file():
            return ""
        try:
            data = target.read_bytes()
        except OSError:
            return ""
        truncated = len(data) > 64_000
        if truncated:
            data = data[:64_000]
        content = data.decode("utf-8", errors="replace")
        if truncated:
            content += "\n\n[truncated after 64000 bytes]"
        return f'<mentioned-file path="{self._xml_escape(path_text)}">\n{self._xml_escape(content)}\n</mentioned-file>'

    def _xml_escape(self, value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def _completion_text_for_command(self, cmd: Any) -> str:
        completion_text = getattr(cmd, "completion_text", None)
        if completion_text:
            return str(completion_text)
        text = f"/{cmd.name}"
        return f"{text} " if getattr(cmd, "params", ()) else text

    def _command_has_required_params(self, cmd: Any) -> bool:
        if bool(getattr(cmd, "completion_only", False)):
            return True
        return any(getattr(param, "required", False) for param in getattr(cmd, "params", ()))

    def _set_prompt_text(self, text: str) -> None:
        self._input.text = text
        row = text.count("\n")
        col = len(text.rsplit("\n", 1)[-1])
        try:
            self._input.move_cursor((row, col), select=False)
        except Exception:
            logger.debug("Could not move prompt cursor", exc_info=True)

    def _record_prompt_history(self, text: str) -> None:
        value = text.strip()
        if not value:
            return
        if not self._prompt_history or self._prompt_history[-1] != value:
            self._prompt_history.append(value)
            if len(self._prompt_history) > 200:
                self._prompt_history = self._prompt_history[-200:]
        self._history_index = None
        self._history_draft = ""

    def _record_recent_command(self, name: str) -> None:
        canonical = "exit" if name == "quit" else name
        self._recent_command_names = [
            canonical,
            *(n for n in self._recent_command_names if n != canonical),
        ][:8]
        self._slash_menu.set_recent_commands(tuple(self._recent_command_names))

    def _prompt_cursor_row(self) -> int | None:
        location = getattr(self._input, "cursor_location", None)
        if location is None:
            return None
        row = getattr(location, "row", None)
        if isinstance(row, int):
            return row
        try:
            return int(location[0])
        except Exception:
            return None

    def _navigate_prompt_history(self, direction: int) -> bool:
        if not self._prompt_history:
            return False

        lines = self._input.text.splitlines() or [""]
        cursor_row = self._prompt_cursor_row()
        if direction < 0 and cursor_row not in (None, 0):
            return False
        if direction > 0 and cursor_row not in (None, len(lines) - 1):
            return False

        if self._history_index is None:
            if direction > 0:
                return False
            self._history_draft = self._input.text
            self._history_index = len(self._prompt_history) - 1
        else:
            self._history_index += direction

        if self._history_index < 0:
            self._history_index = 0
        if self._history_index >= len(self._prompt_history):
            self._history_index = None
            self._set_prompt_text(self._history_draft)
            return True

        self._set_prompt_text(self._prompt_history[self._history_index])
        return True

    def _scroll_log_for_empty_prompt(self, key: str) -> bool:
        """Treat wheel-as-arrow keys as transcript scroll when input is empty.

        With terminal mouse reporting disabled, many terminals translate mouse
        wheel movement in the alternate screen to ``up`` / ``down`` key events.
        Since focus normally stays on the prompt, those events would otherwise
        navigate prompt history instead of scrolling output.
        """
        if key not in {"up", "down"}:
            return False
        if self._input.text.strip():
            return False
        if self._log.max_scroll_y <= 0:
            return False
        if key == "up":
            self._log.action_scroll_up()
            self._pause_history_auto_scroll()
        else:
            self._log.action_scroll_down()
            self._handle_log_scroll()
        return True

    # ---------------- steering ----------------

    def _inject_steering(self, text: str) -> None:
        try:
            self._runtime.ctx.send_message(
                BusMessage(
                    content=text,
                    source="user",
                    target="main",
                    template=STEERING_TEMPLATE,
                )
            )
            self._steering.add(text)
            logger.debug("Steering message injected: %s", text[:50])
        except Exception:
            logger.exception("Failed to inject steering")
            self._sink.show_breadcrumb("→ failed to inject steering — see logs")

    # ---------------- Ctrl+C ----------------

    def action_interrupt(self) -> None:
        # If an agent task is running: cancel it
        if self._agent_task is not None and not self._agent_task.done():
            self._agent_task.cancel()
            self._sink.show_breadcrumb("→ cancelling…")
            self._ctrl_c_at = time.monotonic()
            return
        # Idle: double-press within 2s exits
        now = time.monotonic()
        if now - self._ctrl_c_at < 2.0:
            self.exit()
            return
        self._ctrl_c_at = now
        self._sink.show_breadcrumb("→ press Ctrl+C again to exit")

    # ---------------- scroll handling ----------------

    def _is_at_bottom(self) -> bool:
        """True iff the RichLog is scrolled to the very bottom."""
        return self._log.scroll_y >= max(0.0, self._log.max_scroll_y - 0.5)

    def _on_history_grew(self) -> None:
        """Called by TextualSink whenever a block was committed to RichLog.

        If the user has scrolled away from the bottom, suppress auto-scroll
        and bump the "↓ N new lines" indicator. Otherwise stay sticky.
        """
        # ``call_after_refresh`` so we observe the post-write scroll state.
        self.call_after_refresh(self._update_scroll_indicator_after_write)

    def _on_sink_status_change(self, state: str, detail: str) -> None:
        """Called by TextualSink when the active phase changes.

        ``state`` is one of ``idle | thinking | waiting | tool | text``. ``detail`` is
        a short freeform string (tool name + summary, etc.) shown after the
        spinner.
        """
        try:
            if state == "idle" and self._footer.state == "working":
                state = "waiting"
                detail = detail or "next tool/result"
            self._status.set_status(state, detail)
        except Exception:
            logger.debug("Could not update status bar", exc_info=True)

    def _on_context_update(self, total_tokens: int, context_window_size: int) -> None:
        """Update the lightweight context indicator from SDK usage events."""
        self._current_context_tokens = max(0, int(total_tokens or 0))
        if context_window_size > 0:
            self._context_window_size = int(context_window_size)
        self._refresh_context_status()

    def _refresh_context_status(self) -> None:
        pct = 0.0
        if self._current_context_tokens > 0 and self._context_window_size > 0:
            pct = self._current_context_tokens / self._context_window_size * 100
        try:
            self._status.context_pct = pct
        except Exception:
            logger.debug("Could not update context status", exc_info=True)

    def _on_history_entry_committed(self, entry: _HistoryEntry) -> None:
        if self._restoring_transcript or not self._session_auto_save_enabled():
            return
        if self._transcript is None:
            return
        if entry.kind == "system":
            return
        if entry.kind == "user" and entry.text.lstrip().startswith("/"):
            return
        error = entry.kind == "error"
        if isinstance(entry.block, ToolCallBlock):
            error = bool(entry.block.error)
        self._transcript.append_entry(
            kind=entry.kind,
            label=entry.label,
            text=entry.text,
            error=error,
        )
        if self._footer.state == "working":
            if entry.kind == "tool":
                self._turn_tool_count += 1
            if error:
                self._turn_error_count += 1

    def _save_message_history_snapshot(self) -> None:
        if not self._session_auto_save_enabled() or self._transcript is None:
            return
        if not self._message_history:
            return
        try:
            self._transcript.save_message_history(self._message_history, self._runtime)
        except Exception:
            logger.debug("Could not save textual session message history", exc_info=True)

    def _record_turn_summary(self) -> None:
        if self._transcript is None or not self._turn_started_at:
            return
        self._transcript.record_turn(
            model=self._model_name,
            duration_seconds=time.monotonic() - self._turn_started_at,
            tool_count=self._turn_tool_count,
            error_count=self._turn_error_count,
        )
        self._turn_started_at = 0.0
        self._turn_tool_count = 0
        self._turn_error_count = 0

    def _render_transcript_entries(self, entries: list[dict[str, Any]]) -> None:
        self._restoring_transcript = True
        try:
            self._log.clear()
            self._sink.clear_history_metadata()
            for entry in entries:
                kind = str(entry.get("kind") or "system")
                text = str(entry.get("text") or "")
                label = str(entry.get("label") or kind)
                error = bool(entry.get("error"))
                if kind == "user":
                    self._sink.write_block(UserPromptBlock(text=text))
                elif kind == "assistant":
                    block = ModelTextBlock()
                    block.append(text)
                    self._sink.write_block(block)
                elif kind == "thinking":
                    block = ThinkingBlock()
                    block.append(text)
                    self._sink.write_block(block)
                elif kind == "tool":
                    block = ToolCallBlock(name=label or "tool")
                    block.complete(text, error=error)
                    self._sink.write_block(block)
                elif kind == "error":
                    self._sink.write_block(ErrorBlock(title=label or "error", body=text))
                else:
                    self._sink.show_breadcrumb(text)
        finally:
            self._restoring_transcript = False

    def _resume_session(self, session_ref: str) -> bool:
        if self._transcript is None:
            self._sink.show_breadcrumb("→ sessions are unavailable")
            return False
        target = self._transcript.resolve_session_id(session_ref)
        if target is None:
            self._sink.show_breadcrumb(f"→ session not found: {session_ref or 'latest'}")
            return False
        self._session_id = target
        self._transcript.switch(target)
        try:
            self._message_history = self._transcript.load_message_history()
            self._transcript.restore_context_state(self._runtime)
        except Exception:
            logger.debug("Could not restore textual session state", exc_info=True)
        self._render_transcript_entries(self._transcript.transcript())
        self._sink.show_breadcrumb(f"→ resumed session {target}")
        return True

    def _list_sessions(self) -> None:
        if self._transcript is None:
            self._sink.show_breadcrumb("→ sessions are unavailable")
            return
        listings = self._transcript.listings()
        if not listings:
            self._sink.show_breadcrumb("→ no saved sessions")
            return
        table = Table(show_header=True, box=None, padding=(0, 1), show_edge=False)
        table.add_column("id", style="console.accent.tool", no_wrap=True)
        table.add_column("name", style="console.text.primary", no_wrap=True)
        table.add_column("latest user", style="console.meta", no_wrap=True)
        table.add_column("updated", style="console.meta", no_wrap=True)
        table.add_column("model", style="console.meta", no_wrap=True)
        for item in listings[:20]:
            marker = "*" if item.session_id == self._session_id else ""
            updated = item.updated_at[:19].replace("T", " ") if item.updated_at else ""
            model = item.model.split(" (", 1)[0] if item.model else ""
            table.add_row(
                f"{item.session_id}{marker}",
                truncate_cells(item.name or "(unnamed)", 24),
                truncate_cells(item.latest_user_prompt, 34),
                updated,
                truncate_cells(model, 18),
            )
        self._sink.write_block(SystemBlock(title="/sessions", body=table))

    def _rename_session(self, name: str) -> bool:
        if self._transcript is None:
            self._sink.show_breadcrumb("→ sessions are unavailable")
            return False
        if not name.strip():
            self._sink.show_breadcrumb("→ rename needs a name")
            return False
        self._transcript.rename(name)
        self._sink.show_breadcrumb(f"→ renamed session {self._session_id}")
        return True

    def _export_session_markdown(self, path_text: str) -> bool:
        if self._transcript is None:
            self._sink.show_breadcrumb("→ sessions are unavailable")
            return False
        path = (
            Path(path_text).expanduser() if path_text.strip() else self._cwd / f"yaacli-session-{self._session_id}.md"
        )
        if not path.is_absolute():
            path = (self._cwd / path).resolve()
        try:
            out = self._transcript.export_markdown(path)
        except Exception as exc:
            self._sink.write_block(ErrorBlock(title="/export", body=str(exc)))
            return False
        self._sink.show_breadcrumb(f"→ exported session to {out}")
        return True

    def _update_scroll_indicator_after_write(self) -> None:
        if self._tool_details_active:
            self._render_tool_details_view()
        if self._is_at_bottom() and not self._user_scrolled_up:
            # Sticky to bottom — clear any indicator + ensure auto_scroll on.
            self._log.auto_scroll = True
            self._pending_lines_while_scrolled = 0
            self._scroll_indicator.pending = 0
            return
        # User is scrolled up — keep auto_scroll off and bump pending counter.
        self._log.auto_scroll = False
        self._pending_lines_while_scrolled += 1
        self._scroll_indicator.pending = self._pending_lines_while_scrolled

    def _handle_log_scroll(self) -> None:
        """Manual-scroll callback. Wired via the RichLog's scroll_y watcher."""
        if self._is_at_bottom():
            # User scrolled back to the bottom — re-arm.
            self._log.auto_scroll = True
            self._user_scrolled_up = False
            self._pending_lines_while_scrolled = 0
            self._scroll_indicator.pending = 0
        else:
            # User scrolled away from bottom — pause auto-scroll.
            self._user_scrolled_up = True
            self._log.auto_scroll = False

    def action_scroll_to_bottom(self) -> None:
        if self._tool_details_active:
            self._hide_tool_details_view()
        self._log.scroll_end(animate=False)
        self._log.auto_scroll = True
        self._user_scrolled_up = False
        self._pending_lines_while_scrolled = 0
        self._scroll_indicator.pending = 0

    def action_page_up(self) -> None:
        self._log.action_page_up()

    def action_page_down(self) -> None:
        self._log.action_page_down()

    def action_search_prompt(self) -> None:
        self._set_prompt_text("/search ")
        self._input.focus()

    def action_search_next(self) -> None:
        if self._search_query:
            self._search_history(self._search_query, direction=1)

    def action_search_previous(self) -> None:
        if self._search_query:
            self._search_history(self._search_query, direction=-1)

    def action_jump_previous_user(self) -> None:
        self._jump_history_marker("user", -1)

    def action_jump_previous_assistant(self) -> None:
        self._jump_history_marker("assistant", -1)

    def action_jump_previous_tool(self) -> None:
        self._jump_history_marker("tool", -1)

    def action_jump_next_error(self) -> None:
        self._jump_history_marker("error", 1)

    def action_tool_toggle_details(self) -> None:
        if self._tool_details_active:
            self._hide_tool_details_view()
            return
        if not self._show_tool_details_view():
            self._sink.show_breadcrumb("→ no tool details")

    def action_tool_expand_all(self) -> None:
        if not self._show_tool_details_view():
            self._sink.show_breadcrumb("→ no tool details")

    def action_tool_copy_command(self) -> None:
        tool = self._sink.last_tool()
        command = tool.command_text() if tool is not None else ""
        if not command:
            self._sink.show_breadcrumb("→ no tool command to copy")
            return
        self._copy_text(command)
        self._sink.show_breadcrumb("→ copied tool command")

    def action_tool_copy_output(self) -> None:
        tool = self._sink.last_tool()
        output = tool.output_text() if tool is not None else ""
        if not output:
            self._sink.show_breadcrumb("→ no tool output to copy")
            return
        self._copy_text(output)
        self._sink.show_breadcrumb("→ copied tool output")

    def action_tool_rerun(self) -> None:
        tool = self._sink.last_tool()
        command = tool.command_text() if tool is not None else ""
        if not command:
            self._sink.show_breadcrumb("→ no shell command to rerun")
            return
        self._set_prompt_text(f"Run this command again:\n{command}")
        self._input.focus()

    def _search_history(self, query: str, *, direction: int = 1) -> bool:
        query = query.strip()
        if not query:
            self._sink.show_breadcrumb("→ search needs a query")
            return False
        matches = self._sink.search_entries(query)
        if not matches:
            self._search_query = query
            self._search_matches = []
            self._search_match_index = -1
            self._sink.show_breadcrumb(f"→ no matches for {query!r}")
            return False
        if query != self._search_query or matches != self._search_matches:
            self._search_query = query
            self._search_matches = matches
            self._search_match_index = 0 if direction >= 0 else len(matches) - 1
        else:
            self._search_match_index = (self._search_match_index + (1 if direction >= 0 else -1)) % len(matches)
        entry_index = self._search_matches[self._search_match_index]
        self._pause_history_auto_scroll()
        self._sink.show_breadcrumb(f"→ search {self._search_match_index + 1}/{len(matches)}: {query}")
        self._sink.scroll_to_entry(entry_index)
        self._pause_history_auto_scroll()
        return True

    def _jump_history_marker(
        self,
        marker: str,
        direction: int,
        *,
        skip_entry_index: int | None = None,
    ) -> bool:
        target = self._sink.marker_entry_index(
            marker,
            direction,
            self._log.scroll_y,
            skip_entry_index=skip_entry_index,
        )
        if target is None:
            self._sink.show_breadcrumb(f"→ no {marker} marker")
            return False
        self._pause_history_auto_scroll()
        arrow = "previous" if direction < 0 else "next"
        self._sink.show_breadcrumb(f"→ jumped to {arrow} {marker}")
        self._sink.scroll_to_entry(target)
        self._pause_history_auto_scroll()
        return True

    def _pause_history_auto_scroll(self) -> None:
        self._log.auto_scroll = False
        self._user_scrolled_up = True

    def _show_tool_details_view(self) -> bool:
        if not self._render_tool_details_view():
            return False
        self._tool_details_active = True
        self._log.display = False
        self._tool_details.display = True
        self._live.display = False
        self._tool_details.scroll_home(animate=False)
        self._tool_details.focus()
        return True

    def _hide_tool_details_view(self) -> None:
        self._tool_details_active = False
        self._tool_details.display = False
        self._log.display = True
        self._live.display = True
        self._input.focus()

    def _render_tool_details_view(self) -> bool:
        blocks = self._sink.detail_blocks()
        self._tool_details.clear()
        if not blocks:
            return False

        width = max(40, self._tool_details.size.width or self._log.size.width or 100)
        console = RichConsole(
            theme=build_theme(),
            force_terminal=True,
            color_system="truecolor",
            width=width,
            height=max(1, self._tool_details.size.height or self._log.size.height or 25),
        )
        title = Text()
        title.append("Tool Details", style="console.tool.name")
        title.append(f" · {len(blocks)} blocks", style="console.tool.duration")
        title.append(" · Ctrl+O to return", style="dim")
        self._write_tool_details(console, title, width)

        for index, block in enumerate(blocks, start=1):
            heading = Text()
            heading.append(f"\n#{index} ", style="console.tool.duration")
            heading.append(getattr(block, "name", type(block).__name__), style="bold")
            if isinstance(block, EditBlock):
                heading.append(" · ", style="console.tool.duration")
                heading.append(block.summary_text(), style="console.tool.arg")
            self._write_tool_details(console, heading, width)
            detail = self._expanded_detail_renderable(block, width)
            self._write_tool_details(console, detail, width)
        return True

    def _write_tool_details(
        self,
        console: RichConsole,
        renderable: RenderableType,
        width: int,
    ) -> None:
        self._tool_details.write(
            Segments(list(console.render(renderable))),
            width=width,
        )

    def _expanded_detail_renderable(self, block: Any, width: int) -> RenderableType:
        if not hasattr(block, "render"):
            return Text(str(block))
        if not hasattr(block, "expanded"):
            return block.render(width)
        previous = block.expanded
        block.expanded = True
        try:
            return block.render(width)
        finally:
            block.expanded = previous

    def _copy_text(self, text: str) -> None:
        try:
            self.copy_to_clipboard(text)
        except Exception:
            logger.debug("copy to clipboard failed", exc_info=True)

    # ---------------- turn execution ----------------

    async def _run_turn(self, user_prompt: str) -> None:
        if self._runtime is None:
            self._sink.write_block(ErrorBlock(title="Runtime", body="not initialised"))
            return

        self._footer.state = "working"
        self._turn_started_at = time.monotonic()
        self._turn_tool_count = 0
        self._turn_error_count = 0
        # Show "thinking" before the first model token arrives — gives the
        # user feedback that the request is in flight (previously the
        # status sat at "ready" until a delta showed up).
        self._status.set_status("thinking")
        session = ConsoleSession(sink=self._sink)
        try:
            await self._execute_with_hitl(user_prompt, session)
        except asyncio.CancelledError:
            self._sink.end_text()
            self._sink.end_thinking()
            self._sink.show_breadcrumb("→ cancelled")
        except Exception as exc:
            self._sink.end_text()
            self._sink.end_thinking()
            self._sink.write_block(
                ErrorBlock(
                    title=type(exc).__name__,
                    body=str(exc) or repr(exc),
                )
            )
            logger.exception("Textual turn failed")
        finally:
            # Ensure no dangling transient blocks.
            self._sink.end_text()
            self._sink.end_thinking()
            self._sink.clear_active_operations()
            # Steering items consumed for this turn
            self._steering.clear()
            try:
                self._runtime.ctx.steering_messages.clear()
            except Exception:
                logger.debug("Could not clear steering_messages", exc_info=True)
            self._footer.state = "ready"
            self._status.set_status("idle")
            self._record_turn_summary()
            self._refresh_header()

    async def _execute_with_hitl(self, user_prompt: str, session: ConsoleSession) -> None:
        """Mirror of console_app._execute_with_hitl, adapted for Textual."""
        next_input: str | DeferredToolResults = user_prompt
        first = True
        result = None
        while True:
            async with stream_agent(
                self._runtime,
                user_prompt=next_input if (first and isinstance(next_input, str)) else None,
                message_history=self._message_history if first else None,
                deferred_tool_results=next_input if not isinstance(next_input, str) else None,
                usage_limits=UsageLimits(request_limit=self._config.general.max_requests),
                post_node_hook=emit_context_update,
                resume_on_error=self._config.general.agent_stream_resume_on_error,
                resume_max_attempts=self._config.general.agent_stream_resume_max_attempts,
                resume_prompt=self._config.general.agent_stream_resume_prompt,
            ) as stream:
                await session.stream(stream)
                try:
                    if hasattr(stream, "all_messages") and callable(stream.all_messages):
                        self._message_history = list(stream.all_messages())
                        self._save_message_history_snapshot()
                except Exception:
                    logger.debug("Could not persist message history", exc_info=True)
                run = getattr(stream, "run", None)
                result = getattr(run, "result", None) if run is not None else None

            output = getattr(result, "output", None) if result else None
            if not isinstance(output, DeferredToolRequests):
                return
            if not output.approvals:
                return

            results = await self._collect_approvals(output)
            next_input = results
            first = False

    async def _collect_approvals(self, deferred: DeferredToolRequests) -> DeferredToolResults:
        results = DeferredToolResults()
        for tool_call in deferred.approvals:
            tool_name = tool_call.tool_name
            if tool_name in self._approval_session_grants:
                results.approvals[tool_call.tool_call_id] = True
                self._sink.show_breadcrumb(f"→ auto-approved {tool_name} (granted earlier this session)")
                continue
            try:
                args_summary = json.dumps(tool_call.args, ensure_ascii=False, default=str)[:400]
            except Exception:
                args_summary = repr(tool_call.args)[:400]
            decision, reason = await self.push_screen_wait(HitlModal(tool_name, args_summary))
            if decision == "approve_once":
                results.approvals[tool_call.tool_call_id] = True
                self._sink.show_breadcrumb(f"→ approved {tool_name}")
            elif decision == "approve_all":
                self._approval_session_grants.add(tool_name)
                results.approvals[tool_call.tool_call_id] = True
                self._sink.show_breadcrumb(f"→ approved {tool_name} for the rest of this session")
            else:
                results.approvals[tool_call.tool_call_id] = ToolDenied(reason or "User rejected")
                self._sink.show_breadcrumb(f"→ rejected {tool_name}")
        return results

    # ---------------- slash commands ----------------

    async def _handle_command(self, command: str) -> bool:
        parts = command[1:].split(maxsplit=1)
        name = parts[0].lower() if parts else ""
        args = parts[1].strip() if len(parts) > 1 else ""

        if name in {"exit", "quit"}:
            self._record_recent_command(name)
            self.exit()
            return True

        if name in {"search", "jump"}:
            self._pause_history_auto_scroll()
        command_entry_index = self._sink.history_entry_count()
        self._sink.write_block(UserPromptBlock(text=command))

        if name == "help":
            self._record_recent_command(name)
            from yaacli.console.palette import DEFAULT_COMMANDS, GROUP_ORDER

            grid = Table.grid(padding=(0, 2))
            grid.add_column(style="console.accent.tool", no_wrap=True)
            grid.add_column(style="console.text.primary")
            cmds = sorted(DEFAULT_COMMANDS, key=lambda c: (GROUP_ORDER.index(c.group), c.name))
            for cmd in cmds:
                grid.add_row(f"/{cmd.name}", truncate_cells(cmd.description, 88))
            self._sink.write_block(SystemBlock(title="/help", body=grid))
            return True

        if name == "clear":
            self._record_recent_command(name)
            self._message_history = []
            self._current_context_tokens = 0
            self._refresh_context_status()
            self._log.clear()
            self._sink.clear_history_metadata()
            if self._transcript is not None:
                self._transcript.clear_transcript()
            self._search_query = ""
            self._search_matches = []
            self._search_match_index = -1
            self._sink.clear_active_operations()
            self._sink.show_breadcrumb("→ conversation cleared")
            return True

        if name in {"session", "sessions"}:
            self._record_recent_command(name)
            if args:
                self._resume_session(args)
            else:
                self._list_sessions()
            return True

        if name == "resume":
            self._record_recent_command(name)
            self._resume_session(args or "latest")
            return True

        if name == "rename":
            self._record_recent_command(name)
            self._rename_session(args)
            return True

        if name == "export":
            self._record_recent_command(name)
            self._export_session_markdown(args)
            return True

        if name == "dump":
            self._record_recent_command(name)
            if self._transcript is None:
                self._sink.show_breadcrumb("→ sessions are unavailable")
                return True
            folder = Path(args).expanduser() if args else self._cwd / ".yaacli-session"
            if not folder.is_absolute():
                folder = (self._cwd / folder).resolve()
            self._transcript.dump_to_folder(folder)
            self._sink.show_breadcrumb(f"→ dumped session to {folder}")
            return True

        if name == "load":
            self._record_recent_command(name)
            if self._transcript is None:
                self._sink.show_breadcrumb("→ sessions are unavailable")
                return True
            if not args:
                self._sink.show_breadcrumb("→ load needs a folder")
                return True
            folder = Path(args).expanduser()
            if not folder.is_absolute():
                folder = (self._cwd / folder).resolve()
            if not folder.is_dir():
                self._sink.show_breadcrumb(f"→ not a directory: {folder}")
                return True
            self._transcript.load_from_folder(folder)
            self._message_history = self._transcript.load_message_history()
            self._render_transcript_entries(self._transcript.transcript())
            self._sink.show_breadcrumb(f"→ loaded session from {folder}")
            return True

        if name == "act":
            self._record_recent_command(name)
            self._mode = "ACT"
            self._footer.mode = self._mode
            self._sink.show_breadcrumb("→ switched to ACT mode")
            return True

        if name == "plan":
            self._record_recent_command(name)
            self._mode = "PLAN"
            self._footer.mode = self._mode
            self._sink.show_breadcrumb("→ switched to PLAN mode (no writes, no shell mutations)")
            return True

        if name == "cost":
            self._record_recent_command(name)
            grid = Table.grid(padding=(0, 2))
            grid.add_column("metric", style="console.meta")
            grid.add_column(style="console.text.primary")
            grid.add_row("messages", str(len(self._message_history)))
            grid.add_row("model", str(self._model_name))
            grid.add_row("mode", self._mode)
            self._sink.write_block(SystemBlock(title="/cost", body=grid))
            return True

        if name == "search":
            self._record_recent_command(name)
            self._search_history(args)
            return True

        if name == "jump":
            self._record_recent_command(name)
            marker = args.lower().strip()
            if marker in {"user", "prompt", "prompts"}:
                self._jump_history_marker(
                    "user",
                    -1,
                    skip_entry_index=command_entry_index,
                )
            elif marker in {"assistant", "model"}:
                self._jump_history_marker("assistant", -1)
            elif marker in {"tool", "tools"}:
                self._jump_history_marker("tool", -1)
            elif marker in {"error", "next-error", "errors"}:
                self._jump_history_marker("error", 1)
            else:
                self._sink.show_breadcrumb("→ jump marker must be user, assistant, tool, or error")
            return True

        if name == "model":
            self._record_recent_command(name)
            await self._handle_model_command(args)
            return True

        if name == "skills":
            self._record_recent_command(name)
            self._show_skills(args)
            return True

        if name == "skill":
            self._record_recent_command(name)
            self._show_skill_detail(args)
            return True

        if name == "mcp":
            self._record_recent_command(name)
            self._show_mcp_servers(args)
            return True

        if name == "subagents":
            self._record_recent_command(name)
            self._show_subagents(args)
            return True

        if name == "subagent":
            self._record_recent_command(name)
            self._show_subagent_detail(args)
            return True

        if name in {"delegate", "spawn"}:
            self._record_recent_command(name)
            self._start_subagent_command(name, args)
            return True

        return False

    # ---------------- skills / subagents ----------------

    def _config_dir(self) -> Path:
        if self._config_manager is not None:
            return self._config_manager.config_dir
        return ConfigManager.DEFAULT_CONFIG_DIR

    @staticmethod
    def _matches_query(haystack: str, query: str) -> bool:
        return query.casefold() in haystack.casefold()

    @staticmethod
    def _find_skill(
        skills: list[DiscoveredSkill],
        name: str,
    ) -> DiscoveredSkill | None:
        if not name:
            return None
        for skill in skills:
            if skill.name == name:
                return skill
        name_folded = name.casefold()
        for skill in skills:
            if skill.name.casefold() == name_folded:
                return skill
        return None

    @staticmethod
    def _find_subagent(
        subagents: list[DiscoveredSubagent],
        name: str,
    ) -> DiscoveredSubagent | None:
        if not name:
            return None
        for subagent in subagents:
            if subagent.name == name:
                return subagent
        name_folded = name.casefold()
        for subagent in subagents:
            if subagent.name.casefold() == name_folded:
                return subagent
        return None

    @staticmethod
    def _format_config_value(value: Any, default: str = "(inherit)") -> str:
        if value is None:
            return default
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)

    @staticmethod
    def _format_name_list(value: list[str] | tuple[str, ...] | None, default: str) -> str:
        if not value:
            return default
        return ", ".join(str(item) for item in value)

    def _discover_skills(self) -> list[DiscoveredSkill]:
        return discover_skills(cwd=self._cwd, config_dir=self._config_dir())

    def _discover_subagents(self) -> list[DiscoveredSubagent]:
        return discover_subagents(config=self._config, config_dir=self._config_dir())

    def _load_active_mcp_config(self) -> tuple[MCPConfig | None, Path | None]:
        if self._config_manager is not None:
            return (
                self._config_manager.load_mcp_config(),
                self._config_manager.get_mcp_config_file(),
            )

        project_mcp = self._cwd / ConfigManager.PROJECT_CONFIG_DIR / "mcp.json"
        if project_mcp.exists():
            return load_mcp_config_file(project_mcp), project_mcp
        global_mcp = self._config_dir() / "mcp.json"
        if global_mcp.exists():
            return load_mcp_config_file(global_mcp), global_mcp
        return None, None

    @staticmethod
    def _mcp_target(config: MCPServerConfig) -> str:
        if config.transport == "streamable_http":
            return config.url or "(missing url)"
        parts = [config.command or "(missing command)", *config.args]
        return " ".join(part for part in parts if part)

    def _mcp_approval_label(self, name: str) -> str:
        tools_config = getattr(self._config, "tools", None)
        need_approval = set(getattr(tools_config, "need_approval_mcps", []) or [])
        return "approval" if name in need_approval else "-"

    def _show_mcp_servers(self, query: str = "") -> None:
        query = query.strip()
        try:
            mcp_config, source_path = self._load_active_mcp_config()
        except Exception as exc:
            self._sink.write_block(ErrorBlock(title="/mcp", body=str(exc)))
            return

        servers = dict(getattr(mcp_config, "servers", {}) or {}) if mcp_config else {}
        if query:
            servers = {
                name: config
                for name, config in servers.items()
                if self._matches_query(
                    "\n".join([
                        name,
                        config.description,
                        config.transport,
                        self._mcp_target(config),
                    ]),
                    query,
                )
            }
        if not servers:
            detail = f" matching {query!r}" if query else ""
            source = source_path or (self._config_dir() / "mcp.json")
            self._sink.write_block(
                SystemBlock(
                    title="/mcp",
                    body=Text(
                        f"no MCP servers configured{detail}; config: {source}",
                        style="console.meta",
                    ),
                )
            )
            return

        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="console.accent.tool", no_wrap=True)
        grid.add_column(style="console.meta", no_wrap=True)
        grid.add_column(style="console.meta", no_wrap=True)
        grid.add_column(style="console.meta", no_wrap=True)
        grid.add_column(style="console.text.primary", no_wrap=True)
        grid.add_column(style="console.text.primary")
        for name, config in sorted(servers.items(), key=lambda item: item[0].lower()):
            required = "required" if config.required else "optional"
            grid.add_row(
                truncate_cells(name, 28),
                required,
                self._mcp_approval_label(name),
                config.transport,
                truncate_cells(self._mcp_target(config), 52),
                truncate_cells(config.description or "-", 88),
            )
        source = str(source_path) if source_path is not None else "(unknown source)"
        body = Group(Text(f"config: {source}", style="console.meta"), grid)
        self._sink.write_block(SystemBlock(title="/mcp", body=body))

    def _show_skills(self, query: str = "") -> None:
        query = query.strip()
        skills = self._discover_skills()
        if query:
            skills = [
                skill
                for skill in skills
                if self._matches_query(
                    f"{skill.name}\n{skill.description}\n{skill.path}",
                    query,
                )
            ]
        if not skills:
            detail = f" matching {query!r}" if query else ""
            self._sink.write_block(
                SystemBlock(
                    title="/skills",
                    body=Text(f"no skills found{detail}", style="console.meta"),
                )
            )
            return

        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="console.accent.tool", no_wrap=True)
        grid.add_column(style="console.meta", no_wrap=True)
        grid.add_column(style="console.text.primary")
        for skill in skills:
            grid.add_row(
                truncate_cells(skill.name, 32),
                skill.source,
                truncate_cells(skill.description, 96),
            )
        self._sink.write_block(SystemBlock(title="/skills", body=grid))

    def _show_skill_detail(self, name: str) -> None:
        name = name.strip()
        skill = self._find_skill(self._discover_skills(), name)
        if skill is None:
            self._sink.show_breadcrumb("→ skill needs a valid name; use /skills to list available skills")
            return

        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="console.meta", no_wrap=True)
        grid.add_column(style="console.text.primary")
        grid.add_row("name", skill.name)
        grid.add_row("description", skill.description)
        grid.add_row("source", skill.source)
        grid.add_row("path", str(skill.path))
        body = Group(grid, Text(str(skill.path), style="console.meta"))
        self._sink.write_block(SystemBlock(title=f"/skill {skill.name}", body=body))

    def _show_subagents(self, query: str = "") -> None:
        query = query.strip()
        subagents = self._discover_subagents()
        if query:
            subagents = [
                subagent
                for subagent in subagents
                if self._matches_query(
                    f"{subagent.name}\n{subagent.description}\n{subagent.path}",
                    query,
                )
            ]
        if not subagents:
            detail = f" matching {query!r}" if query else ""
            self._sink.write_block(
                SystemBlock(
                    title="/subagents",
                    body=Text(f"no subagents found{detail}", style="console.meta"),
                )
            )
            return

        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="console.accent.tool", no_wrap=True)
        grid.add_column(style="console.meta", no_wrap=True)
        grid.add_column(style="console.meta", no_wrap=True)
        grid.add_column(style="console.text.primary")
        for subagent in subagents:
            status = "disabled" if subagent.disabled else "enabled"
            model = self._format_config_value(subagent.config.model)
            grid.add_row(
                truncate_cells(subagent.name, 28),
                status,
                truncate_cells(model, 32),
                truncate_cells(subagent.description, 96),
            )
        self._sink.write_block(SystemBlock(title="/subagents", body=grid))

    def _show_subagent_detail(self, name: str) -> None:
        name = name.strip()
        subagent = self._find_subagent(self._discover_subagents(), name)
        if subagent is None:
            self._sink.show_breadcrumb("→ subagent needs a valid name; use /subagents to list configured subagents")
            return

        cfg = subagent.config
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="console.meta", no_wrap=True)
        grid.add_column(style="console.text.primary")
        grid.add_row("name", cfg.name)
        grid.add_row("status", "disabled" if subagent.disabled else "enabled")
        grid.add_row("description", cfg.description)
        grid.add_row("model", self._format_config_value(cfg.model))
        grid.add_row("settings", self._format_config_value(cfg.model_settings, "(default)"))
        grid.add_row("cfg", self._format_config_value(cfg.model_cfg, "(default)"))
        grid.add_row("tools", self._format_name_list(cfg.tools, "all inherited"))
        grid.add_row("optional", self._format_name_list(cfg.optional_tools, "(none)"))
        grid.add_row("path", str(subagent.path))
        body = Group(grid, Text(str(subagent.path), style="console.meta"))
        self._sink.write_block(SystemBlock(title=f"/subagent {cfg.name}", body=body))

    def _start_subagent_command(self, command_name: str, args: str) -> None:
        if self._model_switch_is_blocked():
            self._sink.show_breadcrumb("→ cannot start a subagent while agent is running")
            return

        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            self._sink.show_breadcrumb(f"→ usage: /{command_name} <subagent> <prompt>")
            return

        subagent_name, prompt = parts[0], parts[1].strip()
        subagent = self._find_subagent(self._discover_subagents(), subagent_name)
        if subagent is None:
            self._sink.show_breadcrumb(f"→ unknown subagent: {subagent_name}; use /subagents")
            return
        if subagent.disabled:
            self._sink.show_breadcrumb(f"→ subagent is disabled: {subagent.name}")
            return
        if not prompt:
            self._sink.show_breadcrumb(f"→ usage: /{command_name} <subagent> <prompt>")
            return

        tool_name = "spawn_delegate" if command_name == "spawn" else "delegate"
        agent_prompt = (
            f'Use the `{tool_name}` tool now with subagent_name="{subagent.name}" '
            "and the prompt below. Do not answer from the main agent before using "
            "the tool.\n\n"
            f"{prompt}"
        )
        self._sink.show_breadcrumb(f"→ {command_name} {subagent.name}")
        self._agent_task = asyncio.create_task(self._run_turn(agent_prompt))

    # ---------------- header ----------------

    def _refresh_header(self) -> None:
        self._header.info = HeaderInfo.gather(self._cwd, self._model_name)

    def _short_model_label(self) -> str:
        """Return a short version of the model name for the footer.

        ``model_name`` looks like ``"opus-4.7 (gateway@anthropic:gcp-claude-opus-4-7)"``.
        We keep just the human alias before the parentheses.
        """
        if not self._model_name:
            return ""
        head = self._model_name.split(" (", 1)[0]
        return head.strip() or self._model_name

    @staticmethod
    def _profile_name_from_display(model_name: str) -> str:
        head = model_name.split(" (", 1)[0]
        return head.strip()

    def _resolve_initial_active_model_name(self, explicit_name: str | None) -> str:
        if explicit_name:
            return explicit_name
        getter = getattr(self._config, "get_startup_model_profile", None)
        if callable(getter):
            try:
                name, _profile = getter()
                if name:
                    return str(name)
            except Exception:
                logger.debug("Could not resolve startup model profile", exc_info=True)
        active_model = getattr(getattr(self._config, "general", None), "active_model", "")
        if active_model:
            return str(active_model)
        return self._profile_name_from_display(self._model_name)

    def _get_model_profiles(self) -> dict[str, Any]:
        getter = getattr(self._config, "get_model_profiles", None)
        if callable(getter):
            return dict(getter())
        return dict(getattr(self._config, "models", None) or {})

    def _get_model_profile(self, name: str) -> Any:
        getter = getattr(self._config, "get_model_profile", None)
        if callable(getter):
            return getter(name)
        profiles = self._get_model_profiles()
        if name not in profiles:
            raise KeyError(f"Unknown model profile: {name}")
        return profiles[name]

    @staticmethod
    def _format_model_display_name(name: str, profile: Any) -> str:
        model = str(getattr(profile, "model", "") or "?")
        label = str(getattr(profile, "label", None) or name)
        return f"{label} ({model})"

    def _model_switch_is_blocked(self) -> bool:
        return self._agent_task is not None and not self._agent_task.done()

    async def _handle_model_command(self, args: str) -> None:
        arg = args.strip()
        if not arg:
            self._show_model_list()
            return
        if arg == "current":
            self._show_current_model()
            return
        self._switch_model(arg)

    def _show_model_list(self) -> None:
        profiles = self._get_model_profiles()
        if not profiles:
            self._sink.show_breadcrumb("→ no model profiles configured")
            return

        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="console.state.success", no_wrap=True)
        grid.add_column(style="console.text.primary", no_wrap=True)
        grid.add_column(style="console.meta")
        for prof_name, prof in profiles.items():
            marker = "●" if prof_name == self._active_model_name else " "
            grid.add_row(
                marker,
                truncate_cells(prof_name, 28),
                truncate_cells(getattr(prof, "model", ""), 72),
            )
        self._sink.write_block(SystemBlock(title="/model", body=grid))

    def _show_current_model(self) -> None:
        if not self._active_model_name:
            self._sink.show_breadcrumb("→ no active model configured")
            return
        try:
            profile = self._get_model_profile(self._active_model_name)
        except Exception:
            self._sink.show_breadcrumb("→ active model profile is unavailable")
            return

        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="console.meta", no_wrap=True)
        grid.add_column(style="console.text.primary")
        grid.add_row("name", self._active_model_name)
        label = getattr(profile, "label", None)
        if label:
            grid.add_row("label", str(label))
        grid.add_row("model", str(getattr(profile, "model", "")))
        model_settings = getattr(profile, "model_settings", None)
        model_cfg = getattr(profile, "model_cfg", None)
        grid.add_row(
            "settings",
            str(model_settings) if model_settings is not None else "(default)",
        )
        grid.add_row("cfg", str(model_cfg) if model_cfg is not None else "(default)")
        description = getattr(profile, "description", "")
        if description:
            grid.add_row("description", truncate_cells(str(description), 96))
        self._sink.write_block(SystemBlock(title="/model current", body=grid))

    def _switch_model(self, model_name: str) -> None:
        if self._model_switch_is_blocked():
            self._sink.show_breadcrumb("→ cannot switch model while agent is running")
            return
        try:
            profile = self._get_model_profile(model_name)
        except KeyError:
            self._sink.show_breadcrumb(f"→ unknown model profile: {model_name}")
            return

        try:
            apply_model_profile(self._runtime, profile)
        except Exception as exc:
            self._sink.write_block(
                ErrorBlock(
                    title="model switch failed",
                    message=str(exc),
                    traceback=None,
                )
            )
            return

        self._active_model_name = model_name
        self._model_name = self._format_model_display_name(model_name, profile)
        self._refresh_header()
        self._footer.model_label = self._short_model_label()
        self._sink.show_breadcrumb(f"→ switched model to {model_name}: {getattr(profile, 'model', '')}")


# ---------------------------------------------------------------------------
# Launcher
# ---------------------------------------------------------------------------


async def run_textual_tui(
    config: YaacliConfig,
    config_manager: ConfigManager,
    *,
    verbose: bool = False,
    working_dir: Path | None = None,
) -> str | None:
    """Construct the runtime then run YaacliTextualApp."""
    cwd = working_dir or Path.cwd()
    async with AsyncExitStack() as stack:
        browser = BrowserManager(config.browser)
        await stack.enter_async_context(browser)

        mcp_config = config_manager.load_mcp_config()
        runtime = create_tui_runtime(
            config=config,
            mcp_config=mcp_config,
            browser_manager=browser,
            working_dir=cwd,
            config_dir=config_manager.config_dir,
        )
        await stack.enter_async_context(runtime)

        # Resolve display model name
        model_name: str | None = None
        active_model_name: str | None = None
        try:
            from yaacli.runtime import resolve_startup_model_profile

            active_name, _ = resolve_startup_model_profile(config)
            active_model_name = active_name
            profile = config.get_model_profile(active_name)
            label = getattr(profile, "label", None) or active_name
            model_name = f"{label} ({getattr(profile, 'model', '?')})"
        except Exception:
            logger.debug("Could not resolve startup model profile", exc_info=True)
            model_name = "(unset)"

        oauth_refresh = getattr(config, "oauth_refresh", None)
        if getattr(oauth_refresh, "enabled", False):
            try:
                from ya_oauth_provider import create_oauth_refresh_supervisor_for_models

                supervisor = create_oauth_refresh_supervisor_for_models(
                    (profile.model for profile in config.get_model_profiles().values()),
                    interval_seconds=getattr(oauth_refresh, "interval_seconds", 1800),
                    failure_retry_seconds=getattr(oauth_refresh, "failure_retry_seconds", 60),
                    refresh_on_startup=getattr(oauth_refresh, "refresh_on_startup", True),
                )
                if supervisor is not None:
                    await supervisor.start()
                    stack.push_async_callback(supervisor.shutdown)
                    logger.info(
                        "OAuth refresh supervisor started providers=%s",
                        sorted(supervisor.provider_names),
                    )
            except Exception:
                logger.warning("Failed to start OAuth refresh supervisor", exc_info=True)

        app = YaacliTextualApp(
            config=config,
            config_manager=config_manager,
            runtime=runtime,
            cwd=cwd,
            model_name=model_name,
            active_model_name=active_model_name,
        )
        # Leave terminal mouse reporting off so ordinary left-drag text
        # selection works in the model transcript. Keyboard navigation still
        # covers scrolling, search, jump markers, and command/menu selection.
        await app.run_async(mouse=False)
    return app.session_id if app.has_session_data else None
