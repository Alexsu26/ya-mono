"""Console V2 modal-prompt fallback (kept for ``YAACLI_TUI=console`` etc).

The Textual app at ``yaacli.console.textual_app`` is the primary v2 runtime
and default CLI experience. This file remains for the legacy modal-prompt variant
which prints blocks straight to scrollback and re-spawns a ``PromptSession``
between turns.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolDenied, UsageLimits
from rich.table import Table
from ya_agent_sdk.agents.main import stream_agent

from yaacli.browser import BrowserManager
from yaacli.config import ConfigManager, YaacliConfig
from yaacli.console.adapter import ConsoleSession
from yaacli.console.app import ConsoleApp
from yaacli.console.prompt import ConsolePrompt
from yaacli.hooks import emit_context_update
from yaacli.logging import get_logger
from yaacli.runtime import create_tui_runtime

logger = get_logger(__name__)


@dataclass
class ConsoleTUI:
    """Top-level v2 application: reads input, runs the agent, repeats."""

    config: YaacliConfig
    config_manager: ConfigManager
    working_dir: Path
    verbose: bool = False

    app: ConsoleApp = field(init=False)
    prompt: ConsolePrompt = field(init=False)
    _exit_stack: AsyncExitStack = field(default_factory=AsyncExitStack, init=False)
    _runtime: Any = field(default=None, init=False)
    _browser: Any = field(default=None, init=False)
    _message_history: list[Any] = field(default_factory=list, init=False)
    _mode: str = field(default="ACT", init=False)
    _approval_session_grants: set[str] = field(default_factory=set, init=False)

    async def __aenter__(self) -> ConsoleTUI:
        await self._exit_stack.__aenter__()

        self._browser = BrowserManager(self.config.browser)
        await self._exit_stack.enter_async_context(self._browser)

        mcp_config = self.config_manager.load_mcp_config()
        self._runtime = create_tui_runtime(
            config=self.config,
            mcp_config=mcp_config,
            browser_manager=self._browser,
            working_dir=self.working_dir,
            config_dir=self.config_manager.config_dir,
        )
        await self._exit_stack.enter_async_context(self._runtime)

        # Pull active model name for header
        model_name = "(unset)"
        try:
            from yaacli.runtime import resolve_startup_model_profile

            active_name, _ = resolve_startup_model_profile(self.config)
            profile = self.config.get_model_profile(active_name)
            model_name = f"{active_name} ({getattr(profile, 'model', '?')})"
        except Exception:
            logger.debug("Could not resolve current model profile for header", exc_info=True)

        self.app = ConsoleApp(
            cwd=self.working_dir,
            model_name=model_name,
            mode=self._mode,
        )
        self.prompt = ConsolePrompt()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)

    async def run(self) -> None:
        self.app.show_header()
        self.app.show_breadcrumb("Type / for commands. /exit to quit.")

        while True:
            try:
                text = await self.prompt.read(prompt="> ")
            except (EOFError, KeyboardInterrupt):
                break
            except OSError as exc:
                # Most often: stdin is not a tty (CI / piped input).
                self.app.show_error(
                    "Console requires a TTY",
                    f"Could not read prompt from stdin: {exc}",
                    detail="Run yaacli from an interactive terminal, or use YAACLI_TUI=v1 for the legacy TUI.",
                )
                return

            text = text.strip()
            if not text:
                continue

            if text.startswith("/"):
                handled = await self._handle_command(text)
                if handled:
                    continue
                # Unknown command — fall through and send to the agent

            self.app.show_user_prompt(text)
            await self._run_turn(text)

    async def _handle_command(self, command: str) -> bool:
        """Return True if command was handled (don't fall through)."""
        parts = command[1:].split(maxsplit=1)
        name = parts[0].lower() if parts else ""
        args = parts[1].strip() if len(parts) > 1 else ""

        if name in {"exit", "quit"}:
            self.app.show_breadcrumb("→ goodbye")
            raise EOFError

        if name == "help":
            self.app.show_user_prompt(command)
            from yaacli.console.palette import DEFAULT_COMMANDS, GROUP_ORDER
            grid = Table.grid(padding=(0, 2))
            grid.add_column(style="bold cyan")
            grid.add_column()
            cmds = sorted(DEFAULT_COMMANDS, key=lambda c: (GROUP_ORDER.index(c.group), c.name))
            for cmd in cmds:
                grid.add_row(f"/{cmd.name}", cmd.description)
            self.app.show_system("/help", grid)
            return True

        if name == "clear":
            self.app.show_user_prompt(command)
            self._message_history = []
            self.app.console.clear()
            self.app.show_header()
            self.app.show_breadcrumb("→ conversation cleared")
            return True

        if name == "act":
            self.app.show_user_prompt(command)
            self._mode = "ACT"
            self.app.mode = "ACT"
            self.app.show_breadcrumb("→ switched to ACT mode")
            return True

        if name == "plan":
            self.app.show_user_prompt(command)
            self._mode = "PLAN"
            self.app.mode = "PLAN"
            self.app.show_breadcrumb(
                "→ switched to PLAN mode (no writes, no shell mutations)"
            )
            return True

        if name == "cost":
            self.app.show_user_prompt(command)
            grid = Table.grid(padding=(0, 2))
            grid.add_column("metric", style="bold")
            grid.add_column()
            grid.add_row("messages", str(len(self._message_history)))
            grid.add_row("model", str(self.app.model_name))
            grid.add_row("mode", str(self.app.mode))
            self.app.show_system("/cost", grid)
            return True

        if name == "model":
            self.app.show_user_prompt(command)
            profiles = getattr(self.config, "models", None) or {}
            grid = Table.grid(padding=(0, 2))
            grid.add_column(style="bold cyan")
            grid.add_column()
            grid.add_column(style="dim")
            for prof_name, prof in profiles.items():
                marker = "●" if prof_name == self.app.model_name else " "
                grid.add_row(marker, prof_name, getattr(prof, "model", ""))
            self.app.show_system("/model", grid)
            if args:
                self.app.show_breadcrumb(
                    f"→ switching model to {args} is not implemented in v2 yet"
                )
            return True

        return False

    async def _run_turn(self, user_prompt: str) -> None:
        if self._runtime is None:
            self.app.show_error("Runtime", "Agent runtime is not initialised.")
            return

        self.app.open_turn()
        session = ConsoleSession(sink=self.app)
        try:
            await self._execute_with_hitl(user_prompt, session)
        except asyncio.CancelledError:
            self.app.end_text()
            self.app.end_thinking()
            self.app.show_breadcrumb("→ cancelled")
        except Exception as exc:
            self.app.end_text()
            self.app.end_thinking()
            self.app.show_error(
                f"{type(exc).__name__}",
                str(exc) or repr(exc),
            )
            logger.exception("Console turn failed")
        finally:
            self.app.close_turn()

    async def _execute_with_hitl(self, user_prompt: str, session: ConsoleSession) -> None:
        """HITL inner loop — runs the agent, resumes on DeferredToolRequests."""
        next_input: str | DeferredToolResults = user_prompt
        first = True
        result = None
        while True:
            async with stream_agent(
                self._runtime,
                user_prompt=next_input if (first and isinstance(next_input, str)) else None,
                message_history=self._message_history if first else None,
                deferred_tool_results=next_input if not isinstance(next_input, str) else None,
                usage_limits=UsageLimits(request_limit=self.config.general.max_requests),
                post_node_hook=emit_context_update,
                resume_on_error=self.config.general.agent_stream_resume_on_error,
                resume_max_attempts=self.config.general.agent_stream_resume_max_attempts,
                resume_prompt=self.config.general.agent_stream_resume_prompt,
            ) as stream:
                await session.stream(stream)
                # Persist message history once per turn
                try:
                    if hasattr(stream, "all_messages") and callable(stream.all_messages):
                        self._message_history = list(stream.all_messages())
                except Exception:
                    logger.debug("Could not persist message history", exc_info=True)
                # Final structured output, if any
                run = getattr(stream, "run", None)
                result = getattr(run, "result", None) if run is not None else None

            output = getattr(result, "output", None) if result else None
            if not isinstance(output, DeferredToolRequests):
                return

            if not output.approvals:
                return

            # Got approvals — collect from user, then continue
            user_response = await self._collect_approvals(output)
            next_input = user_response
            first = False

    async def _collect_approvals(self, deferred: DeferredToolRequests) -> DeferredToolResults:
        """Render an approval block per pending tool call and read y/a/n."""
        results = DeferredToolResults()
        approvals = list(deferred.approvals)
        # Inline-prompt each in turn so the agent sees consistent ordering
        for tool_call in approvals:
            tool_name = tool_call.tool_name
            if tool_name in self._approval_session_grants:
                results.approvals[tool_call.tool_call_id] = True
                self.app.show_breadcrumb(
                    f"→ auto-approved {tool_name} (granted earlier this session)"
                )
                continue

            try:
                args_str = json.dumps(tool_call.args, ensure_ascii=False, default=str)[:200]
            except Exception:
                args_str = repr(tool_call.args)[:200]
            self.app.show_hitl(tool_name, args_str)
            decision, reason = await self._read_approval_key(tool_name)

            if decision == "approve_once":
                results.approvals[tool_call.tool_call_id] = True
                self.app.show_breadcrumb(f"→ approved {tool_name}")
            elif decision == "approve_all":
                self._approval_session_grants.add(tool_name)
                results.approvals[tool_call.tool_call_id] = True
                self.app.show_breadcrumb(
                    f"→ approved {tool_name} for the rest of this session"
                )
            else:
                results.approvals[tool_call.tool_call_id] = ToolDenied(
                    reason or "User rejected"
                )
                self.app.show_breadcrumb(f"→ rejected {tool_name}")
        return results

    async def _read_approval_key(self, tool_name: str) -> tuple[str, str | None]:
        """Read a single approval response. Returns (decision, reason|None).

        decision ∈ {approve_once, approve_all, reject}
        """
        # We use a fresh PromptSession so the slash-completer doesn't
        # interfere; the keystroke prompt is a single-line free-text input
        # to keep parity with v1's denial-reason capture.
        session: PromptSession[str] = PromptSession()
        prompt = FormattedText([
            ("bold yellow", f"approve {tool_name}? "),
            ("dim", "[y]es / [a]ll-this-session / [n]o (with reason): "),
        ])
        try:
            response = await session.prompt_async(prompt)
        except (EOFError, KeyboardInterrupt):
            return ("reject", "User cancelled")

        text = response.strip()
        if not text:
            return ("approve_once", None)
        first = text[0].lower()
        if first == "a":
            return ("approve_all", None)
        if first == "y":
            return ("approve_once", None)
        # Anything else = reject; rest of the line becomes the reason
        reason = text[1:].strip() if len(text) > 1 and text[1] in {":", " "} else text
        return ("reject", reason or "User rejected")


async def run_console_tui(
    config: YaacliConfig,
    config_manager: ConfigManager,
    *,
    verbose: bool = False,
    working_dir: Path | None = None,
) -> str | None:
    """Entry point used by ``yaacli.cli`` when ``YAACLI_TUI=console``."""
    async with ConsoleTUI(
        config=config,
        config_manager=config_manager,
        working_dir=working_dir or Path.cwd(),
        verbose=verbose,
    ) as tui:
        await tui.run()
    return None
