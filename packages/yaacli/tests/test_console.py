"""Tests for the v2 console summarizers and block renderers."""

from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console
from yaacli.console.app import ConsoleApp
from yaacli.console.blocks import (
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
from yaacli.console.blocks.tool_call import summarize_args, summarize_result
from yaacli.console.theme import build_theme


def _render(block) -> str:
    buf = io.StringIO()
    console = Console(theme=build_theme(), file=buf, width=100, force_terminal=False)
    console.print(block.render(100))
    return buf.getvalue()


def test_design_tokens_define_transcript_first_visual_language() -> None:
    from yaacli.console.theme import CONSOLE_STYLES

    required = {
        "console.surface.base",
        "console.surface.raised",
        "console.surface.overlay",
        "console.text.primary",
        "console.text.secondary",
        "console.text.muted",
        "console.border.subtle",
        "console.border.active",
        "console.accent.user",
        "console.accent.assistant",
        "console.accent.tool",
        "console.state.waiting",
        "console.state.running",
        "console.state.success",
        "console.state.error",
        "console.heading.turn",
        "console.heading.block",
        "console.meta",
        "console.code.bg",
    }

    assert required <= set(CONSOLE_STYLES)


def test_cjk_truncation_respects_terminal_cell_width() -> None:
    from rich.cells import cell_len
    from yaacli.console.design import truncate_cells

    value = "packages/输出/工具调用/长文件名.py"
    truncated = truncate_cells(value, 18)

    assert cell_len(truncated) <= 18
    assert truncated.endswith("…")
    assert "输" in truncated or "出" in truncated


def test_transcript_first_blocks_share_rail_and_role_labels() -> None:
    # Unified block system: every block leads with a ``●`` dot and an
    # uppercase role label; body content aligns to the same 2-col gutter.
    user = _render(UserPromptBlock(text="请总结 packages/yaacli"))
    assert "YOU" in user
    assert "●" in user

    assistant = ModelTextBlock()
    assistant.append("你好，**世界**")
    assistant_out = _render(assistant)
    assert "ASSISTANT" in assistant_out
    assert "●" in assistant_out
    assert "你好" in assistant_out

    tool = ToolCallBlock(name="Bash", args={"command": "pytest", "cwd": "/repo"})
    tool.complete({"stdout": "ok\n", "stderr": "", "exit_code": 0, "cwd": "/repo"})
    tool_out = _render(tool)
    assert "Bash" in tool_out
    assert "pytest" in tool_out
    assert "done" in tool_out

    error = _render(ErrorBlock(title="pytest failed", body="3 failures"))
    assert "●" in error
    assert "ERROR" in error
    assert "3 failures" in error
    assert "╭" not in error

    system = _render(SystemBlock(title="/sessions", body="clean verify", boxed=False))
    assert "SYSTEM" in system
    assert "/sessions" in system
    assert "clean verify" in system


# ---------------------------- summarize_args ---------------------------------


def test_summarize_args_bash_command_dict() -> None:
    out = summarize_args("Bash", {"command": "ls -la"})
    assert out == "ls -la"


def test_summarize_args_bash_command_json_string() -> None:
    out = summarize_args("Bash", '{"command": "echo hello"}')
    assert out == "echo hello"


def test_summarize_args_truncates_long_bash_command() -> None:
    out = summarize_args("Bash", {"command": "x" * 200})
    assert out.endswith("…")
    assert len(out) <= 80


def test_summarize_args_redacts_passwords() -> None:
    out = summarize_args("CustomTool", {"username": "alice", "password": "supersecret"})
    assert "supersecret" not in out
    assert "***" in out


def test_summarize_args_read_uses_path() -> None:
    assert summarize_args("Read", {"path": "src/x.py"}) == "src/x.py"
    assert summarize_args("Read", {"file_path": "src/y.py"}) == "src/y.py"


def test_summarize_args_replaces_newlines_inline() -> None:
    out = summarize_args("Bash", {"command": "echo a\necho b"})
    assert "\n" not in out
    assert "⏎" in out


# ---------------------------- summarize_result -------------------------------


def test_summarize_result_read_counts_lines() -> None:
    out = summarize_result("Read", "line1\nline2\nline3", error=False)
    assert out == "3 lines"


def test_summarize_result_handles_none() -> None:
    assert summarize_result("Bash", None, error=False) == "no output"


def test_summarize_result_error_returns_first_line() -> None:
    out = summarize_result("Bash", "Error: bad thing\ntraceback ...", error=True)
    assert out == "Error: bad thing"


def test_summarize_result_shell_multiline_reports_line_count_and_tail() -> None:
    out = summarize_result("Bash", "build started\nrunning tests\ndone", error=False)
    assert out == "3 lines · last: done"


# ---------------------------- block renderers --------------------------------


def test_user_prompt_block_renders_text_with_anchor() -> None:
    block = UserPromptBlock(text="hello world")
    output = _render(block)
    assert "hello world" in output
    assert "●" in output


def test_tool_call_block_running_includes_spinner_label() -> None:
    block = ToolCallBlock(name="Bash", args={"command": "sleep 1"})
    output = _render(block)
    assert "Bash" in output
    assert "sleep 1" in output
    # Running line includes "running"
    assert "running" in output


def test_tool_call_block_completed_replaces_spinner() -> None:
    block = ToolCallBlock(name="Read", args={"path": "x.py"})
    block.complete("a\nb\nc\n", error=False)
    output = _render(block)
    assert "Read" in output
    assert "x.py" in output
    # Card shows a line-numbered preview of the output, not a spinner.
    assert "a" in output
    assert "running" not in output


def test_tool_call_block_completed_includes_done_status() -> None:
    block = ToolCallBlock(name="Bash", args={"command": "make test"})
    block.complete("line 1\nline 2\ndone", error=False)
    output = _render(block)
    assert "Bash" in output
    assert "done" in output
    # Preview surfaces the actual output lines inside the card body.
    assert "line 1" in output
    assert "line 2" in output


def test_tool_call_block_collapses_shell_details_by_default() -> None:
    block = ToolCallBlock(
        name="Bash",
        args={"command": "make test", "cwd": "/repo"},
    )
    block.complete(
        {
            "stdout": "ok\n",
            "stderr": "warning\n",
            "exit_code": 0,
            "duration": 1.25,
            "cwd": "/repo",
        },
        error=False,
    )
    output = _render(block)
    assert "Bash" in output
    assert "done" in output
    # Collapsed card shows a short preview but not the labelled detail panel.
    assert "shell details" not in output
    assert "command " not in output


def test_tool_call_block_expanded_shell_details_separate_streams() -> None:
    block = ToolCallBlock(
        name="Bash",
        args={"command": "make test", "cwd": "/repo"},
        expanded=True,
    )
    block.complete(
        {
            "stdout": "ok\n",
            "stderr": "warning\n",
            "exit_code": 2,
            "duration": 1.25,
            "cwd": "/repo",
        },
        error=True,
    )
    output = _render(block)
    assert "command" in output
    assert "make test" in output
    assert "cwd" in output
    assert "/repo" in output
    assert "exit code" in output
    assert "2" in output
    assert "stdout" in output
    assert "ok" in output
    assert "stderr" in output
    assert "warning" in output


def test_tool_call_block_failed_uses_cross() -> None:
    block = ToolCallBlock(name="Bash", args={"command": "false"})
    block.complete("Error: command failed", error=True)
    output = _render(block)
    assert "✗" in output
    assert "failed" in output


def test_thinking_block_uses_gutter_per_line() -> None:
    block = ThinkingBlock()
    block.append("first thought\nsecond thought")
    output = _render(block)
    assert "THINKING" in output
    assert "first thought" in output
    assert "second thought" in output


def test_edit_block_renders_diff_summary(tmp_path: Path) -> None:
    block = EditBlock.single(
        str(tmp_path / "x.py"),
        "def foo():\n    return 1\n",
        "def foo():\n    return 2\n",
    )
    output = _render(block)
    assert "Edit" in output
    assert "+1" in output
    assert "−1" in output  # MINUS SIGN
    assert "+    return 2" in output
    assert "-    return 1" in output


def test_edit_block_compacts_large_diff_with_hidden_line_count(tmp_path: Path) -> None:
    old = "\n".join(f"old line {i}" for i in range(120)) + "\n"
    new = "\n".join(f"new line {i}" for i in range(120)) + "\n"
    block = EditBlock.single(str(tmp_path / "large.py"), old, new)
    output = _render(block)
    assert "large.py" in output
    assert "+120" in output
    assert "−120" in output
    assert "hidden" in output
    assert len(output.splitlines()) < 100


def test_edit_block_can_collapse_hunk_details(tmp_path: Path) -> None:
    block = EditBlock.single(
        str(tmp_path / "x.py"),
        "def foo():\n    return 1\n",
        "def foo():\n    return 2\n",
    )
    block.expanded = False

    output = _render(block)

    assert "1 hunk" in output
    assert "@@ " in output
    assert "+1" in output
    assert "−1" in output
    assert "+    return 2" not in output
    assert "-    return 1" not in output


def test_edit_block_toggle_expands_collapsed_hunks(tmp_path: Path) -> None:
    block = EditBlock.single(
        str(tmp_path / "x.py"),
        "def foo():\n    return 1\n",
        "def foo():\n    return 2\n",
    )
    block.expanded = False
    block.toggle_expanded()

    output = _render(block)

    assert "+    return 2" in output
    assert "-    return 1" in output


def test_todo_block_uses_status_glyphs() -> None:
    block = TodoBlock(
        items=[
            TodoItem("a", status="completed"),
            TodoItem("b", status="in_progress"),
            TodoItem("c", status="pending"),
        ]
    )
    output = _render(block)
    assert "✓" in output
    assert "▶" in output
    assert "◯" in output
    assert "1/3" in output


def test_task_block_renders_children() -> None:
    block = TaskBlock(
        title="root",
        children=[
            TaskChild("agent_a", "step 1", status="done", summary="ok", duration=0.5),
            TaskChild("agent_b", "step 2", status="error", summary="boom", duration=1.0),
        ],
    )
    block.state.is_terminal = True
    output = _render(block)
    assert "root" in output
    assert "agent_a" in output
    assert "agent_b" in output
    assert "ok" in output
    assert "boom" in output


def test_error_block_marks_state_error() -> None:
    block = ErrorBlock(title="Bad", body="went wrong")
    assert block.state.error is True
    assert block.is_terminal()
    output = _render(block)
    assert "Bad" in output
    assert "went wrong" in output


def test_error_block_labels_detail_for_scannability() -> None:
    block = ErrorBlock(title="Runtime", body="request failed", detail="Traceback line 1\nTraceback line 2")
    output = _render(block)
    assert "Runtime" in output
    assert "request failed" in output
    assert "detail" in output.lower()
    assert "Traceback line 1" in output


def test_hitl_block_lists_choices() -> None:
    block = HitlBlock(tool_name="Bash", summary="rm -rf /")
    output = _render(block)
    assert "Bash" in output
    assert "rm -rf /" in output
    assert "approve" in output
    assert "reject" in output


def test_system_block_renders_with_box() -> None:
    block = SystemBlock(title="/cost", body="hello", boxed=True)
    output = _render(block)
    assert "/cost" in output
    assert "hello" in output
    # Has a box border somewhere
    assert "─" in output or "╭" in output


def test_model_text_block_appends_chunks() -> None:
    block = ModelTextBlock()
    block.append("hello ")
    block.append("world")
    output = _render(block)
    assert "hello" in output
    assert "world" in output


# ---------------------------- ConsoleApp orchestration -----------------------


def _capture(app: ConsoleApp) -> str:
    return app.console.file.getvalue() if hasattr(app.console.file, "getvalue") else ""


def test_console_app_lifecycle_smoke() -> None:
    app = ConsoleApp(cwd=Path.cwd(), model_name="opus-4.7", mode="ACT")
    # Replace console with a captured one for testing
    buf = io.StringIO()
    app.console = Console(theme=build_theme(), file=buf, width=100, force_terminal=False)
    from yaacli.console.stream import LiveStream

    app.stream = LiveStream(app.console)

    app.show_user_prompt("hi")
    app.open_turn()
    app.handle_text_delta("hello there")
    app.end_text()
    app.handle_tool_call_start("t1", "Read", {"path": "x.py"})
    app.handle_tool_call_complete("t1", "line\n")
    app.close_turn()

    out = buf.getvalue()
    assert "●" in out
    assert "YOU" in out
    assert "hi" in out
    assert "hello there" in out
    assert "Read" in out
    assert "x.py" in out
