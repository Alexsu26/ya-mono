"""Drive the Textual app headlessly and export an SVG snapshot.

Verifies overall layout — header, transcript gutter alignment, tamed
scrollbar, and composer alignment — without a real terminal.

Usage:  uv run python scripts/tui_snapshot.py [out.svg]
"""
# ruff: noqa: RUF001  — intentional CJK sample text in demo strings

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


def _stub_config(theme: str = "graphite") -> SimpleNamespace:
    return SimpleNamespace(
        general=SimpleNamespace(
            max_requests=10,
            agent_stream_resume_on_error=False,
            agent_stream_resume_max_attempts=0,
            agent_stream_resume_prompt="",
        ),
        models={},
        display=SimpleNamespace(theme=theme, code_theme="dark"),
    )


def _stub_runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.ctx = MagicMock()
    runtime.ctx.steering_messages = []
    runtime.ctx.send_message = MagicMock()
    return runtime


async def _run(out: Path, theme: str = "graphite") -> None:
    from yaacli.console.blocks import (
        ModelTextBlock,
        ThinkingBlock,
        ToolCallBlock,
        UserPromptBlock,
    )
    from yaacli.console.textual_app import YaacliTextualApp

    app = YaacliTextualApp(
        config=_stub_config(theme),
        runtime=_stub_runtime(),
        cwd=Path.cwd(),
        model_name="claude-opus-4-8",
    )
    async with app.run_test(size=(96, 32)) as pilot:
        await pilot.pause()
        sink = app._sink

        user = UserPromptBlock(text="帮我把 fetch() 改成异步的，并加上错误处理。")
        sink.write_block(user)

        think = ThinkingBlock()
        think.append("Read the file, wrap IO in try/except, await the calls.")
        sink.write_block(think)

        asst = ModelTextBlock()
        asst.append("我先读取文件，然后：\n\n- 改成 `async def fetch()`\n- 用 `await client.get(...)`\n- 包一层错误处理\n")
        sink.write_block(asst)

        tool = ToolCallBlock(name="Bash", args={"command": "rg -n 'def fetch' src/"})
        tool.complete({"stdout": "src/api.py:12:def fetch(url):", "stderr": "", "exit_code": 0}, error=False)
        sink.write_block(tool)

        await pilot.pause()
        app.save_screenshot(str(out))
    print(f"wrote {out}")


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tui_snapshot.svg")
    theme = sys.argv[2] if len(sys.argv) > 2 else "graphite"
    asyncio.run(_run(out, theme))


if __name__ == "__main__":
    main()
