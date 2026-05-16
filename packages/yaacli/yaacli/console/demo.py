"""Synthetic runner — drives ConsoleApp from a canned event stream.

Two entry points:

* ``run_demo()`` — exercises every block kind once in roughly the same
  shape as a real session. Used both for visual verification ("does this
  look right?") and as a regression check ("does it still render?").

* ``main()`` — invoked via ``python -m yaacli.console.demo``.

Phase 1 self-test uses this exclusively: no agent SDK, no network, no
prompt input. The point is to confirm the visual contract.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from yaacli.console.app import ConsoleApp
from yaacli.console.blocks import TaskChild, TodoItem


async def run_demo(*, fast: bool = False, with_prompt: bool = False) -> None:
    """Walk through every block kind.

    Args:
        fast: Skip artificial delays — useful for CI / capture.
        with_prompt: After the demo, hand control to a ``ConsolePrompt`` so
            the user can try the slash palette interactively.
    """
    delay = 0.0 if fast else 0.4

    app = ConsoleApp(cwd=Path.cwd(), model_name="opus-4.7", mode="ACT")

    app.show_header()
    app.show_user_prompt("数据库里 admin 用户怎么登录的？")

    app.open_turn()
    try:
        # Streaming text + thinking + a couple of synchronous tool calls
        for chunk in ("我先看一下", " 数据库 schema", " 和相关代码。\n"):
            app.handle_text_delta(chunk)
            await asyncio.sleep(delay)
        app.end_text()

        app.handle_tool_call_start("t1", "Bash", {"command": "which psql && psql --version"})
        await asyncio.sleep(delay * 2)
        app.handle_tool_call_complete("t1", "exit code 1\nno output\n", error=False)

        app.handle_tool_call_start("t2", "Bash", {"command": "ls /opt/homebrew/opt | grep -i postgres"})
        await asyncio.sleep(delay * 2)
        app.handle_tool_call_complete("t2", "exit code 1\n", error=False)

        # In-flight + interleaved thinking
        app.handle_tool_call_start("t3", "Bash", {"command": ".venv/bin/python -c 'import asyncpg'"})
        for chunk in (
            "嗯，前两个 shell 都返回了 1。",
            " 看来本机没有 psql 客户端，",
            " 我直接用 python 的 driver 试试。",
        ):
            app.handle_thinking_delta(chunk)
            await asyncio.sleep(delay / 2)
        app.end_thinking()
        await asyncio.sleep(delay)
        app.handle_tool_call_complete("t3", "asyncpg ok\n", error=False)

        app.handle_tool_call_start(
            "t4", "Bash", {"command": ".venv/bin/python <<'EOF'\\nimport psycopg... (+435 chars)"}
        )
        await asyncio.sleep(delay * 3)
        # Long-ish output: the summarizer collapses it
        app.handle_tool_call_complete(
            "t4",
            "('public', 'admin_impersonations')\n('public', 'agents')\n"
            "('public', 'artifacts')\n('public', 'browse_logs')\n"
            "('public', 'cache_entries')\n('public', 'documents')\n"
            "('public', 'jobs')\n('public', 'lark_oauth_states')\n"
            "(... 24 more)\n",
            error=False,
        )

        app.handle_tool_call_start("t5", "Read", {"path": "packages/metahub-service/auth.py"})
        await asyncio.sleep(delay)
        # Synthetic 142-line content
        app.handle_tool_call_complete("t5", "\n" * 141 + "X\n", error=False)

        # Final markdown output
        for chunk in (
            "\n",
            "## admin 用户信息\n\n",
            "- **id**: `henryz`\n",
            "- **email**: hmzhu@ubiquantpartners.com\n",
            "- **role**: admin\n",
            "- **password_hash**: NULL（未设置密码）\n\n",
            "数据库里只有一个 admin 用户，但 metahub 是通过 **Lark OAuth** ",
            "登录的，所以 `password_hash` 字段为空。\n",
        ):
            app.handle_text_delta(chunk)
            await asyncio.sleep(delay / 3)
        app.end_text()
    finally:
        app.close_turn()

    # Editing block
    app.show_breadcrumb("→ user follow-up")
    app.show_user_prompt("帮我改一下 auth.py 里那个错的方法名")
    app.open_turn()
    try:
        app.handle_tool_call_start("t6", "Bash", {"command": "grep -rn get_user packages/metahub-service/"})
        await asyncio.sleep(delay)
        app.handle_tool_call_complete("t6", "1 match: packages/metahub-service/auth.py:88\n")
        app.show_edit(
            "packages/metahub-service/auth.py",
            edits=[
                (
                    "def authenticate(email: str, password: str):\n"
                    "    user = db.get_user(email)\n"
                    "    if not user:\n"
                    '        raise AuthError("not found")\n'
                    "    return user\n",
                    "def authenticate(email: str, password: str):\n"
                    "    user = db.get_user_by_email(email)\n"
                    "    if not user:\n"
                    '        raise AuthError("invalid credentials")\n'
                    "    return user\n",
                ),
            ],
        )
        for chunk in ("已经把方法名改成 ", "`get_user_by_email` 并优化了报错文案。\n"):
            app.handle_text_delta(chunk)
            await asyncio.sleep(delay / 3)
        app.end_text()
    finally:
        app.close_turn()

    # Todos + a sub-task
    app.show_todos([
        TodoItem("调查 admin 登录机制", status="completed"),
        TodoItem("确认密码哈希算法", status="completed"),
        TodoItem("起草 admin 设置密码的 SQL", status="in_progress"),
        TodoItem("在 staging 验证", status="pending"),
        TodoItem("写文档", status="pending"),
    ])

    app.show_task(
        "审计 schema 中的 NULL 列",
        [
            TaskChild(
                "search_agent",
                "在 *.sql 中搜索 ALTER TABLE",
                status="done",
                summary="14 matches · 6 files",
                duration=1.3,
            ),
            TaskChild("reasoning", "分析迁移顺序", status="done", summary="done", duration=2.1),
        ],
    )

    # Failure surface
    app.open_turn()
    try:
        app.handle_tool_call_start("t7", "Bash", {"command": "pytest packages/ya-claw/tests/"})
        await asyncio.sleep(delay)
        app.handle_tool_call_complete(
            "t7",
            "AssertionError: expected /workspace, got /tmp/workspace\n  packages/ya-claw/tests/test_workspace.py:42\n",
            error=True,
        )
        app.show_error(
            "Bash · pytest",
            "AssertionError: expected /workspace, got /tmp/workspace",
            detail="packages/ya-claw/tests/test_workspace.py:42",
        )
        for chunk in ("看起来是 ", "`DOCKER_HOST_WORKSPACE_DIR` ", "没设好，我修一下。\n"):
            app.handle_text_delta(chunk)
            await asyncio.sleep(delay / 3)
        app.end_text()
    finally:
        app.close_turn()

    # System block (mock /cost)
    from rich.table import Table

    table = Table.grid(padding=(0, 2))
    table.add_column("model", style="bold")
    table.add_column("input")
    table.add_column("output")
    table.add_column("cost")
    table.add_row("opus-4.7", "12.4k", "3.2k", "$0.71")
    table.add_row("haiku-4.5", "8.9k", "1.1k", "$0.13")
    app.show_system("/cost", table)

    # HITL block — render only; user input is wired in Phase 3
    app.show_hitl(
        "Bash",
        "rm -rf .venv && uv sync",
        tag="dangerous · needs approval",
    )

    if with_prompt:
        from yaacli.console.prompt import ConsolePrompt

        prompt = ConsolePrompt()
        app.show_breadcrumb("(demo over — try typing /act, /cost, etc.)")
        try:
            while True:
                value = await prompt.read(prompt="> ")
                if value.strip() in {"/exit", "/quit"}:
                    break
                app.show_user_prompt(value)
        except (EOFError, KeyboardInterrupt):
            pass


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="yaacli console v2 demo")
    parser.add_argument("--fast", action="store_true", help="skip delays")
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="after the demo, open the slash-palette prompt for interactive testing",
    )
    args = parser.parse_args()
    asyncio.run(run_demo(fast=args.fast, with_prompt=args.prompt))


if __name__ == "__main__":
    main()
