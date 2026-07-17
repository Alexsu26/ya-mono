"""Render-capture harness for the streaming console blocks.

Renders each block type at a fixed width through a themed Rich Console and
prints the result, so we can eyeball gutter alignment / colours / indentation
as plain (ANSI) text — no real terminal needed.

Usage:  uv run python scripts/tui_capture.py [theme_name] [width]
"""
# ruff: noqa: RUF001  — intentional CJK sample text in demo strings

from __future__ import annotations

import sys

from rich.console import Console
from yaacli.console.blocks import (
    ModelTextBlock,
    ThinkingBlock,
    ToolCallBlock,
    UserPromptBlock,
)
from yaacli.console.theme import build_theme, list_themes


def _rule(console: Console, title: str) -> None:
    console.print(f"[dim]{'─' * 4} {title} {'─' * (60 - len(title))}[/dim]")


def main() -> None:
    theme_name = sys.argv[1] if len(sys.argv) > 1 else "tokyo-night"
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 88

    console = Console(theme=build_theme(theme_name), force_terminal=True, color_system="truecolor", width=width)
    console.print(f"\n[bold]THEME = {theme_name}   WIDTH = {width}   (themes: {', '.join(list_themes())})[/bold]\n")

    # ---- user
    _rule(console, "user_prompt")
    user = UserPromptBlock(text="帮我把这个函数重构成异步的，并加上错误处理。")
    console.print(user.render(width))

    # ---- thinking
    _rule(console, "thinking")
    think = ThinkingBlock()
    think.append("The user wants an async refactor. I should read the file first,\n")
    think.append("then wrap the body in a try/except and await the IO calls.")
    console.print(think.render(width))

    # ---- assistant
    _rule(console, "model_text (assistant)")
    asst = ModelTextBlock()
    asst.append("我先读取文件，然后做以下改动：\n\n")
    asst.append("- 把 `def fetch()` 改成 `async def fetch()`\n")
    asst.append("- 用 `await client.get(...)` 替换同步调用\n")
    asst.append("- 包一层 `try/except` 处理 `httpx.HTTPError`\n\n")
    asst.append("```python\nasync def fetch(url: str) -> dict:\n    resp = await client.get(url)\n    return resp.json()\n```\n")
    console.print(asst.render(width))

    # ---- tool call: running
    _rule(console, "tool_call (running)")
    tool_run = ToolCallBlock(name="Bash", args={"command": "rg -n 'def fetch' src/"})
    console.print(tool_run.render(width, frame=4))

    # ---- tool call: done
    _rule(console, "tool_call (done)")
    tool_done = ToolCallBlock(name="Bash", args={"command": "rg -n 'def fetch' src/"})
    tool_done.complete({"stdout": "src/api.py:12:def fetch(url):\nsrc/api.py:40:def fetch_all():", "stderr": "", "exit_code": 0}, error=False)
    console.print(tool_done.render(width))

    # ---- tool call: failed
    _rule(console, "tool_call (failed)")
    tool_err = ToolCallBlock(name="Bash", args={"command": "pytest -x"})
    tool_err.complete({"stdout": "", "stderr": "2 failed", "exit_code": 1}, error=True)
    console.print(tool_err.render(width))

    console.print()


if __name__ == "__main__":
    main()
