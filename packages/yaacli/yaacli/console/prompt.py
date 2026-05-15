"""Modal prompt session — replaces the always-on Composer pane.

The PromptSession lives between turns. While an agent is running, no input
area is on screen; when the turn ends, ``read()`` re-spawns the prompt
underneath the last printed block.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style

from yaacli.console.palette import DEFAULT_COMMANDS, SLASH_PALETTE_STYLES, SlashCommand, SlashCompleter


class ConsolePrompt:
    """Wraps a PromptSession and exposes a single ``read()`` coroutine."""

    def __init__(
        self,
        get_commands: Callable[[], Iterable[SlashCommand]] | None = None,
    ) -> None:
        self._history = InMemoryHistory()
        self._session: PromptSession[str] = PromptSession(
            history=self._history,
            multiline=False,
            mouse_support=False,
            complete_while_typing=True,
            completer=SlashCompleter(
                get_commands=get_commands or (lambda: DEFAULT_COMMANDS)
            ),
            style=Style.from_dict(SLASH_PALETTE_STYLES),
            key_bindings=self._build_key_bindings(),
        )
        self._multiline = False

    def _build_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("escape", "enter")
        def _newline(event: object) -> None:
            buf = self._session.app.current_buffer if self._session.app else None
            if buf is not None:
                buf.insert_text("\n")

        @kb.add(Keys.ControlJ)
        def _newline_ctrl_j(event: object) -> None:
            buf = self._session.app.current_buffer if self._session.app else None
            if buf is not None:
                buf.insert_text("\n")

        return kb

    async def read(self, *, prompt: str = "> ") -> str:
        formatted_prompt = FormattedText([("bold", prompt)])
        return await self._session.prompt_async(
            formatted_prompt,
            multiline=False,
            wrap_lines=True,
        )
