"""Tool-call block — the streaming console's most-used renderable.

Format:
    ⏺ <ToolName> · <arg-summary>
      ⎿ ⠼ running 1.4s              # in-flight
      ⎿ <result-summary> · <duration>   # done
      ✗ failed · exit 1 · 12.3s     # failed
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from rich.box import ROUNDED
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from yaacli.console.blocks.base import BaseBlock, BlockKind
from yaacli.console.design import GUTTER_WIDTH, truncate_cells
from yaacli.console.glyphs import GLYPHS, SPINNER_FRAMES

# How many lines of tool output to preview inside the card body.
_PREVIEW_LINES = 6
_PREVIEW_LINE_LEN = 110

_MAX_ARG_LEN = 80
_MAX_RESULT_LEN = 100
_MAX_DETAIL_CHARS = 4_000
_SENSITIVE_KEYS = {"password", "secret", "token", "api_key", "apikey", "authorization"}
_SHELL_TOOL_NAMES = {"bash", "shell", "shell_exec", "execute_bash"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in _SENSITIVE_KEYS else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _truncate_inline(text: str, limit: int) -> str:
    text = text.replace("\n", " ⏎ ")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _parse_json_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _shell_command(args: Any) -> str:
    parsed = _parse_json_mapping(args)
    if not parsed:
        return ""
    return str(parsed.get("command") or parsed.get("cmd") or "")


def _shell_cwd(args: Any, result: Any) -> str:
    result_map = _parse_json_mapping(result) or {}
    args_map = _parse_json_mapping(args) or {}
    return str(result_map.get("cwd") or args_map.get("cwd") or "")


def _shell_exit_code(result: Any) -> Any:
    parsed = _parse_json_mapping(result)
    if not parsed:
        return None
    for key in ("exit_code", "returncode", "status"):
        if key in parsed:
            return parsed[key]
    return None


def _shell_streams(result: Any) -> tuple[str, str]:
    parsed = _parse_json_mapping(result)
    if not parsed:
        return (str(result or ""), "")
    stdout = parsed.get("stdout")
    stderr = parsed.get("stderr")
    output = parsed.get("output")
    if stdout is None and output is not None:
        stdout = output
    return (str(stdout or ""), str(stderr or ""))


def _line_count(text: str) -> int:
    return len(text.splitlines()) if text.strip() else 0


def _truncate_block(text: str, limit: int = _MAX_DETAIL_CHARS) -> tuple[str, int]:
    if len(text) <= limit:
        return text, 0
    return text[:limit], len(text) - limit


def summarize_args(name: str, args: Any) -> str:
    """Tool-specific one-line argument summary.

    Args may arrive as a dict, a JSON string, or arbitrary repr-able value.
    """
    if args is None:
        return ""
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except (json.JSONDecodeError, ValueError):
            return _truncate_inline(args, _MAX_ARG_LEN)
        args = parsed

    args = _redact(args)
    lname = name.lower()

    if isinstance(args, dict):
        if lname in _SHELL_TOOL_NAMES:
            cmd = args.get("command") or args.get("cmd") or ""
            return _truncate_inline(str(cmd), _MAX_ARG_LEN)
        if lname in {"read", "read_file"}:
            return str(args.get("path") or args.get("file_path") or "")
        if lname in {"write", "write_file"}:
            return str(args.get("path") or args.get("file_path") or "")
        if lname in {"edit", "multi_edit", "multiedit"}:
            return str(args.get("path") or args.get("file_path") or "")
        if lname in {"grep", "search"}:
            return _truncate_inline(str(args.get("pattern") or args.get("query") or ""), _MAX_ARG_LEN)
        if lname in {"task", "subagent", "spawn_agent"}:
            agent_name = args.get("subagent_type") or args.get("agent") or args.get("name") or ""
            prompt = args.get("prompt") or args.get("description") or ""
            label = f"{agent_name}: {prompt}" if agent_name else str(prompt)
            return _truncate_inline(label, _MAX_ARG_LEN)
        if lname in {"glob"}:
            return _truncate_inline(str(args.get("pattern") or ""), _MAX_ARG_LEN)
        # Generic dict
        return _truncate_inline(json.dumps(args, ensure_ascii=False, default=str), _MAX_ARG_LEN)

    return _truncate_inline(str(args), _MAX_ARG_LEN)


def summarize_result(name: str, content: Any, error: bool) -> str:
    """Tool-specific one-line result summary."""
    if content is None:
        return "no output"

    text = content if isinstance(content, str) else str(content)
    if not text.strip():
        return "no output"

    if error:
        first = text.strip().splitlines()[0]
        return _truncate_inline(first, _MAX_RESULT_LEN)

    lname = name.lower()
    if lname in _SHELL_TOOL_NAMES and _parse_json_mapping(content) is not None:
        exit_code = _shell_exit_code(content)
        stdout, stderr = _shell_streams(content)
        parts: list[str] = []
        if exit_code is not None:
            parts.append(f"exit {exit_code}")
        if stdout.strip():
            nlines = len(stdout.splitlines()) or 1
            parts.append(f"out {nlines} lines")
        if stderr.strip():
            nlines = len(stderr.splitlines()) or 1
            parts.append(f"err {nlines} lines")
        if parts:
            return " · ".join(parts)

    nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lname in _SHELL_TOOL_NAMES and len(nonempty_lines) > 1:
        tail = _truncate_inline(nonempty_lines[-1], 60)
        return f"{len(nonempty_lines)} lines · last: {tail}"
    if lname in {"read", "read_file"}:
        nlines = len(text.splitlines()) or 1
        return f"{nlines} lines"
    if lname in {"write", "write_file"}:
        nlines = len(text.splitlines()) or 1
        return f"wrote {nlines} lines"
    if lname in {"grep", "search"}:
        # naive — works for "N matches" outputs
        nmatches = sum(1 for line in text.splitlines() if line.strip())
        return f"{nmatches} matches"
    if lname in {"glob"}:
        nfiles = sum(1 for line in text.splitlines() if line.strip())
        return f"{nfiles} files"

    first_nonempty = next(iter(nonempty_lines), "")
    return _truncate_inline(first_nonempty or text, _MAX_RESULT_LEN)


@dataclass
class ToolCallBlock(BaseBlock):
    """A single tool call. Mutable while running; finalize() freezes it."""

    name: str = ""
    args: Any = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    result: Any = None
    error: bool = False
    expanded: bool = False

    def __post_init__(self) -> None:
        self.kind = BlockKind.TOOL_CALL
        super().__post_init__()

    @property
    def duration(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return max(0.0, end - self.started_at)

    def update_args(self, args: Any) -> None:
        """Allow late-arriving args to refine the rendered summary."""
        self.args = args

    def toggle_expanded(self) -> None:
        self.expanded = not self.expanded

    def complete(self, result: Any, *, error: bool = False) -> None:
        self.result = result
        self.error = error
        self.finished_at = time.monotonic()
        self.finalize(error=error)

    def command_text(self) -> str:
        if self.name.lower() in _SHELL_TOOL_NAMES:
            return _shell_command(self.args)
        return summarize_args(self.name, self.args)

    def output_text(self) -> str:
        if self.name.lower() in _SHELL_TOOL_NAMES:
            stdout, stderr = _shell_streams(self.result)
            return "\n".join(part for part in (stdout, stderr) if part)
        return self.result if isinstance(self.result, str) else str(self.result or "")

    def _render_details(self, width: int) -> RenderableType:
        if self.name.lower() in _SHELL_TOOL_NAMES:
            return self._render_shell_details(width)

        body = Text()
        body.append("args\n", style="console.tool.tag")
        args_text = json.dumps(_redact(self.args), ensure_ascii=False, indent=2, default=str)
        args_text, hidden_args = _truncate_block(args_text)
        body.append(args_text or "(none)", style="console.tool.arg")
        if hidden_args:
            body.append(
                f"\n… {hidden_args} args chars hidden; use /export to show more",
                style="console.tool.duration",
            )
        body.append("\n\nresult\n", style="console.tool.tag")
        result_text = self.output_text()
        result_text, hidden_result = _truncate_block(result_text)
        body.append(result_text or "(no output)", style="console.tool.result")
        if hidden_result:
            body.append(
                f"\n… {hidden_result} output chars hidden; use /export to show more",
                style="console.tool.duration",
            )
        return Panel(
            body,
            title="details",
            title_align="left",
            border_style="dim",
            padding=(0, 1),
            width=max(40, min(width - 2, 120)),
        )

    def _render_shell_details(self, width: int) -> RenderableType:
        body = Text()
        command = self.command_text()
        cwd = _shell_cwd(self.args, self.result)
        exit_code = _shell_exit_code(self.result)
        stdout, stderr = _shell_streams(self.result)

        body.append("command ", style="console.tool.tag")
        body.append(command or "(unknown)", style="console.tool.arg")
        if cwd:
            body.append("\ncwd ", style="console.tool.tag")
            body.append(cwd, style="console.tool.arg")
        if exit_code is not None:
            body.append("\nexit code ", style="console.tool.tag")
            exit_style = "console.dot.success" if str(exit_code) == "0" else "console.dot.error"
            body.append(str(exit_code), style=exit_style)
        body.append(f"\nduration {self.duration:.1f}s", style="console.tool.duration")

        stdout_text, hidden_stdout = _truncate_block(stdout)
        stderr_text, hidden_stderr = _truncate_block(stderr)
        body.append("\n\nstdout\n", style="console.tool.tag")
        body.append(stdout_text or "(empty)", style="console.tool.result")
        if hidden_stdout:
            body.append(
                f"\n… {hidden_stdout} stdout chars hidden; use /export to show more",
                style="console.tool.duration",
            )
        body.append("\n\nstderr\n", style="console.tool.tag")
        body.append(stderr_text or "(empty)", style="console.tool.result")
        if hidden_stderr:
            body.append(
                f"\n… {hidden_stderr} stderr chars hidden; use /export to show more",
                style="console.tool.duration",
            )

        return Panel(
            body,
            title="shell details",
            title_align="left",
            border_style="dim",
            padding=(0, 1),
            width=max(40, min(width - 2, 120)),
        )

    def _status_parts(self, *, frame: int) -> tuple[str, str, str]:
        """Return ``(marker, status_label, status_style)`` for the header."""
        if not self.is_terminal():
            return SPINNER_FRAMES[frame % len(SPINNER_FRAMES)], "running", "console.state.running"
        if self.error:
            return GLYPHS.CROSS, "failed", "console.state.error"
        return GLYPHS.CHECK, "done", "console.state.success"

    def _header_row(self, width: int, *, frame: int) -> Table:
        """The card's top row: ``<name>  <arg>            <status>  <dur>``."""
        marker, status, status_style = self._status_parts(frame=frame)
        summary = summarize_args(self.name, self.args)

        right = Text()
        right.append(f"{marker} ", style=status_style)
        right.append(status, style=status_style)
        right.append(f"  {self.duration:.1f}s", style="console.tool.duration")

        left = Text()
        left.append(self.name, style="console.tool.name")
        if summary:
            left.append("  ", style="console.tool.duration")
            left.append(truncate_cells(summary, max(12, width - 30)), style="console.tool.arg")

        row = Table.grid(expand=True)
        row.add_column(justify="left", ratio=1)
        row.add_column(justify="right", no_wrap=True)
        row.add_row(left, right)
        return row

    def _preview_body(self) -> Text | None:
        """A short, line-numbered output preview for the card body."""
        if not self.is_terminal():
            return None
        text = self.output_text().strip("\n")
        if not text.strip():
            return None
        lines = text.splitlines()
        shown = lines[:_PREVIEW_LINES]
        body = Text()
        result_style = "console.state.error" if self.error else "console.tool.result"
        for index, raw in enumerate(shown):
            if index:
                body.append("\n")
            body.append(f"{index + 1:>3} ", style="console.tool.duration")
            body.append(truncate_cells(raw, _PREVIEW_LINE_LEN), style=result_style)
        hidden = len(lines) - len(shown)
        if hidden > 0:
            body.append(f"\n    … +{hidden} lines · ctrl-o for details", style="console.tool.tag")
        return body

    def render(self, width: int, *, frame: int = 0) -> RenderableType:
        card_width = max(32, min(width - GUTTER_WIDTH, 118))
        parts: list[RenderableType] = [self._header_row(card_width - 2, frame=frame)]

        if self.expanded:
            parts.append(self._render_details(card_width))
        else:
            preview = self._preview_body()
            if preview is not None:
                parts.append(preview)

        border_style = "console.state.error" if (self.is_terminal() and self.error) else "console.code.border"
        card = Panel(
            Group(*parts) if len(parts) > 1 else parts[0],
            box=ROUNDED,
            border_style=border_style,
            padding=(0, 1),
            width=card_width,
        )
        # Indent the whole card under the unified block gutter.
        return Padding(card, (0, 0, 0, GUTTER_WIDTH))
