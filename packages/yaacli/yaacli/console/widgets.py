"""Custom Textual widgets for the v2 streaming console."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from rich.cells import cell_len
from rich.console import Console as RichConsole
from rich.console import Group, RenderableType
from rich.segment import Segments
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Static, TextArea

from yaacli.console.design import pad_cells, truncate_cells
from yaacli.console.glyphs import GLYPHS, SPINNER_FRAMES
from yaacli.console.header import HeaderInfo, render_header
from yaacli.console.theme import build_theme

_IGNORED_PATH_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


_TERMINAL_ASSOCIATED_TEXT_RE = re.compile(r"(?:\^)?(?:\x1b)?\[\d+;;((?:\d+:)*\d+)u")
_TERMINAL_ASSOCIATED_TEXT_EXACT_RE = re.compile(r"^(?:\^)?(?:\x1b)?\[\d+;;((?:\d+:)*\d+)u$")
_TERMINAL_ASSOCIATED_TEXT_FLUSH_DELAY = 0.12


def decode_terminal_associated_text(text: str) -> str:
    """Decode terminal CSI-u associated text payloads into Unicode text."""

    def replace_match(match: re.Match[str]) -> str:
        chars: list[str] = []
        for raw_codepoint in match.group(1).split(":"):
            try:
                codepoint = int(raw_codepoint, 10)
            except ValueError:
                return match.group(0)
            if not 0 <= codepoint <= 0x10FFFF:
                return match.group(0)
            chars.append(chr(codepoint))
        return "".join(chars)

    return _TERMINAL_ASSOCIATED_TEXT_RE.sub(replace_match, text)


def _is_terminal_associated_text_prefix(text: str) -> bool:
    if text == "^":
        return True
    if text.startswith("^"):
        text = text[1:]
    if not text.startswith("["):
        return False
    body = text[1:]
    if not body:
        return True

    digit_count = 0
    while digit_count < len(body) and body[digit_count].isdigit():
        digit_count += 1
    if digit_count == 0:
        return False
    rest = body[digit_count:]
    if not rest:
        return True
    if rest == ";":
        return True
    if not rest.startswith(";;"):
        return False

    payload = rest[2:]
    if not payload:
        return True
    if payload.endswith("u"):
        return _TERMINAL_ASSOCIATED_TEXT_EXACT_RE.fullmatch(f"[0;;{payload}") is not None
    if "u" in payload:
        return False
    parts = payload.split(":")
    return all(part.isdigit() for part in parts[:-1]) and (parts[-1] == "" or parts[-1].isdigit())


@dataclass(frozen=True)
class PathMentionItem:
    """One file or directory candidate for ``@path`` completion."""

    display: str
    path: Path
    is_dir: bool


@dataclass(frozen=True)
class SlashArgumentItem:
    """One argument completion candidate inside a slash command."""

    command: str
    name: str
    description: str
    completion_text: str
    usage: str
    group: str = "SUBAGENT"
    completion_only: bool = True


def _render_themed(renderable: RenderableType, *, width: int = 200) -> Segments:
    """Resolve theme styles by rendering through a private Rich Console.

    Textual's ``Static.update()`` parses style names as colors, which breaks
    when our blocks/headers use semantic style tokens like ``console.dot``.
    We render through a themed console here and hand Textual the resolved
    Segments — Textual treats Segments as opaque and renders them verbatim.
    """
    console = RichConsole(
        theme=build_theme(),
        force_terminal=True,
        color_system="truecolor",
        width=width,
    )
    return Segments(list(console.render(renderable)))


class HeaderBar(Static):
    """Top docked status line — cwd, branch, model, context%, cost."""

    DEFAULT_CSS = """
    HeaderBar {
        dock: top;
        height: 1;
        padding: 0 1;
        background: #171a23;
        color: #d8dee9;
    }
    """

    info: reactive[HeaderInfo | None] = reactive(None)

    def watch_info(self, info: HeaderInfo | None) -> None:
        if info is None:
            self.update(Text(""))
        else:
            self.update(_render_themed(render_header(info), width=self.size.width or 200))


class FooterHint(Static):
    """Bottom docked help/status line.

    Two-zone layout:
        ┌──────────────────────────────────────────────────────────┐
        │ ↵ send · / commands · ctrl-c cancel  │  model · 18% · $0 ACT · ready │
        └──────────────────────────────────────────────────────────┘
        ←──── left: keyboard hints ────→        ←─ right: state ──→
    """

    DEFAULT_CSS = """
    FooterHint {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: #171a23;
        color: #6f778a;
    }
    """

    mode: reactive[str] = reactive("ACT")
    state: reactive[str] = reactive("ready")  # ready | working
    model_label: reactive[str] = reactive("")
    context_pct: reactive[float] = reactive(0.0)
    cost_str: reactive[str] = reactive("")
    spinner_frame: reactive[int] = reactive(0)

    def watch_mode(self, _value: str) -> None:
        self.refresh_text()

    def watch_state(self, _value: str) -> None:
        self.refresh_text()

    def watch_model_label(self, _value: str) -> None:
        self.refresh_text()

    def watch_context_pct(self, _value: float) -> None:
        self.refresh_text()

    def watch_cost_str(self, _value: str) -> None:
        self.refresh_text()

    def watch_spinner_frame(self, _value: int) -> None:
        # Only repaints text — width doesn't change.
        if self.state == "working":
            self.refresh_text()

    def on_mount(self) -> None:
        self.refresh_text()
        # 10 Hz spinner tick when working.
        self.set_interval(1.0 / 10.0, self._tick_spinner)

    def _tick_spinner(self) -> None:
        if self.state == "working":
            self.spinner_frame = (self.spinner_frame + 1) % len(SPINNER_FRAMES)

    def refresh_text(self) -> None:
        # Build left and right halves; pad between with spaces sized to fill.
        right = Text()
        if self.model_label:
            right.append(truncate_cells(self.model_label, 28), style="bold #aeb6c8")
            right.append("  ·  ", style="#6f778a")
        if self.context_pct > 0:
            right.append(f"{self.context_pct:.0f}%", style="#6f778a")
            right.append("  ·  ", style="#6f778a")
        if self.cost_str:
            right.append(self.cost_str, style="#6f778a")
            right.append("  ·  ", style="#6f778a")
        mode_style = "bold #8bd5a4" if self.mode.upper() == "ACT" else "bold #7aa2f7"
        right.append(self.mode.upper(), style=mode_style)
        right.append(" · ", style="#6f778a")
        if self.state == "working":
            spin = SPINNER_FRAMES[self.spinner_frame % len(SPINNER_FRAMES)]
            right.append(f"working {spin}", style="#7dcfff")
        else:
            right.append("ready", style="#9ece6a")

        width = self.size.width or 80
        right_len = right.cell_len
        available_left = max(10, width - right_len - 3)
        hint_options = (
            " Enter sends · Shift+Enter newline · / commands · @ files · Ctrl+C cancel",
            " Enter sends · Shift+Enter newline · / · @ · Ctrl+C",
            " Enter · Shift+Enter · / · @",
        )
        hint = next(
            (option for option in hint_options if cell_len(option) <= available_left),
            truncate_cells(hint_options[-1], available_left),
        )
        left = Text(hint, style="#6f778a")

        # Compute padding to push right half to the far edge.
        left_len = left.cell_len
        gap = max(2, width - left_len - right_len - 1)
        out = Text()
        out.append_text(left)
        out.append(" " * gap)
        out.append_text(right)
        self.update(out)


class ScrollIndicator(Static):
    """Floating "↓ N new lines" pill that appears when the user has scrolled
    away from the bottom while new history is arriving.

    Press End in the app to jump back to the bottom and dismiss.
    """

    DEFAULT_CSS = """
    ScrollIndicator {
        dock: bottom;
        height: 1;
        width: auto;
        max-width: 30;
        padding: 0 2;
        background: $accent;
        color: $background;
        text-style: bold;
        display: none;
        layer: overlay;
    }
    ScrollIndicator.has-pending {
        display: block;
    }
    """

    pending: reactive[int] = reactive(0)

    def watch_pending(self, value: int) -> None:
        if value <= 0:
            self.remove_class("has-pending")
            self.update("")
            return
        self.add_class("has-pending")
        self.update(Text(f" ↓ {value} new output below · End ", style="bold"))


class SteeringList(Static):
    """Bottom-of-output collapsed steering list, hidden when empty."""

    DEFAULT_CSS = """
    SteeringList {
        dock: bottom;
        height: auto;
        max-height: 5;
        padding: 0 1;
        background: #171a23;
        color: #d8dee9;
        display: none;
    }
    SteeringList.has-items {
        display: block;
    }
    """

    items: reactive[tuple[str, ...]] = reactive(())

    def watch_items(self, items: tuple[str, ...]) -> None:
        if not items:
            self.remove_class("has-items")
            self.update(Text(""))
            return
        self.add_class("has-items")
        out = Text()
        for i, item in enumerate(items):
            if i > 0:
                out.append("\n")
            out.append(f"{GLYPHS.DIAMOND} ", style="bold magenta")
            out.append(item.splitlines()[0][:120] if item else "")
        self.update(_render_themed(out, width=self.size.width or 120))

    def add(self, message: str) -> None:
        self.items = (*self.items, message)

    def clear(self) -> None:
        self.items = ()


class SlashMenu(Static):
    """Popup-style command palette docked above the input.

    Visible only when the prompt starts with ``/``. Filters the registered
    slash commands by what the user has typed so far, highlights one row
    as the current selection, and exposes ``move_up`` / ``move_down`` /
    ``selected_command`` for the app to drive via key bindings.
    """

    DEFAULT_CSS = """
    SlashMenu {
        dock: bottom;
        height: auto;
        max-height: 20;
        padding: 0 1;
        background: #1d2130;
        color: #d8dee9;
        display: none;
        border-top: solid #7aa2f7;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
    }
    SlashMenu.has-items {
        display: block;
    }
    """

    selected_index: reactive[int] = reactive(0)
    visible_commands: reactive[tuple[Any, ...]] = reactive(())
    MAX_RENDERED_ROWS: ClassVar[int] = 19

    def __init__(self) -> None:
        super().__init__("")
        self._all_commands: tuple[Any, ...] = ()
        self._subagent_provider: Callable[[], Any] | None = None

    def set_all_commands(self, commands: tuple[Any, ...]) -> None:
        self._all_commands = commands

    def set_subagent_provider(self, provider: Callable[[], Any]) -> None:
        self._subagent_provider = provider

    def set_recent_commands(self, command_names: tuple[str, ...]) -> None:
        # Slash menu layout is intentionally stable across opens; recent command
        # history is accepted for compatibility but does not affect rendering.
        _ = command_names

    def update_query(self, query: str) -> None:
        """Update the visible command list based on the typed query.

        ``query`` is the prompt text *including* the leading ``/``.
        Empty / non-slash query collapses the menu.
        """
        if not query.startswith("/"):
            self._hide()
            return
        if "\n" in query:
            self._hide()
            return

        argument_items = self._argument_items(query[1:])
        if argument_items is not None:
            if not argument_items:
                self._hide()
                return
            self.visible_commands = argument_items
            self.selected_index = min(self.selected_index, len(argument_items) - 1)
            self.add_class("has-items")
            self._repaint()
            return

        raw_query = query[1:].lower().strip()
        if " " in raw_query:
            # Once the user has typed unsupported args, suppress the menu.
            self._hide()
            return
        matches = tuple(
            sorted(
                (cmd for cmd in self._all_commands if self._matches(cmd, raw_query)),
                key=lambda cmd: self._match_sort_key(cmd, raw_query),
            )
        )
        if not matches:
            self._hide()
            return
        self.visible_commands = matches
        self.selected_index = min(self.selected_index, len(matches) - 1)
        self.add_class("has-items")
        self._repaint()

    def _argument_items(self, body: str) -> tuple[SlashArgumentItem, ...] | None:
        command, sep, remainder = body.partition(" ")
        command = command.lower()
        if sep != " " or command not in {"delegate", "spawn"}:
            return None
        if remainder.endswith(" ") and remainder.strip():
            return ()
        prefix = remainder.strip()
        if any(ch.isspace() for ch in prefix):
            return ()

        choices = tuple(self._subagent_provider() if self._subagent_provider else ())
        items: list[SlashArgumentItem] = []
        for choice in choices:
            if bool(getattr(choice, "disabled", False)):
                continue
            name = str(getattr(choice, "name", ""))
            if not name:
                continue
            if prefix and not name.lower().startswith(prefix.lower()):
                continue
            description = str(getattr(choice, "description", ""))
            items.append(
                SlashArgumentItem(
                    command=command,
                    name=name,
                    description=description,
                    completion_text=f"/{command} {name} ",
                    usage=f"{name}",
                )
            )
        return tuple(sorted(items, key=lambda item: item.name.lower()))

    def _hide(self) -> None:
        self.visible_commands = ()
        self.selected_index = 0
        self.remove_class("has-items")
        self.update("")

    def watch_visible_commands(self, _value: tuple[Any, ...]) -> None:
        if self._all_commands:
            self._repaint()

    def watch_selected_index(self, _value: int) -> None:
        if self.visible_commands:
            self._repaint()

    def move_up(self) -> None:
        if not self.visible_commands:
            return
        self.selected_index = (self.selected_index - 1) % len(self.visible_commands)

    def move_down(self) -> None:
        if not self.visible_commands:
            return
        self.selected_index = (self.selected_index + 1) % len(self.visible_commands)

    @property
    def selected_command(self) -> Any:
        if not self.visible_commands:
            return None
        return self.visible_commands[self.selected_index % len(self.visible_commands)]

    @property
    def is_open(self) -> bool:
        return bool(self.visible_commands)

    def _matches(self, cmd: Any, query: str) -> bool:
        if not query:
            return True
        name = str(getattr(cmd, "name", "")).lower()
        description = str(getattr(cmd, "description", "")).lower()
        params = " ".join(str(getattr(param, "name", "")).lower() for param in getattr(cmd, "params", ()))
        deep_search = len(query) >= 2
        return (
            name.startswith(query)
            or (deep_search and query in name)
            or (deep_search and query in description)
            or (deep_search and query in params)
        )

    def _match_sort_key(self, cmd: Any, query: str) -> tuple[int, int, int, str]:
        name = str(getattr(cmd, "name", "")).lower()
        description = str(getattr(cmd, "description", "")).lower()
        group_order = {
            "MODE": 0,
            "SESSION": 1,
            "WORKSPACE": 2,
            "INSPECT": 3,
            "OTHER": 4,
        }
        if not query or name.startswith(query):
            score = 0
        elif query in name:
            score = 1
        elif len(query) >= 2 and query in description:
            score = 2
        else:
            score = 3
        return (score, 99, group_order.get(str(getattr(cmd, "group", "")), 99), name)

    def _usage_for(self, cmd: Any) -> str:
        usage_override = getattr(cmd, "usage", None)
        if usage_override:
            return str(usage_override)
        usage = f"/{getattr(cmd, 'name', '')}"
        for param in getattr(cmd, "params", ()):
            name = getattr(param, "name", "")
            if getattr(param, "required", True):
                usage += f" <{name}>"
            else:
                usage += f" [{name}]"
        return usage

    def _repaint(self) -> None:
        if not self.visible_commands:
            self.update("")
            return
        selected = self.selected_index % len(self.visible_commands)
        start, end = self._render_window(selected)
        out = Text()
        for i, cmd in enumerate(self.visible_commands[start:end], start=start):
            is_sel = i == selected
            prefix = "▸ " if is_sel else "  "
            row_style = "bold reverse" if is_sel else ""
            out.append(prefix, style="bold #7aa2f7" if is_sel else "#6f778a")
            out.append(
                pad_cells(self._usage_for(cmd), 24),
                style=("bold #9aa5ce" if is_sel else "#89ddff"),
            )
            group = getattr(cmd, "group", "")
            if group:
                out.append(pad_cells(group, 10), style="#6f778a")
            out.append(truncate_cells(cmd.description, 80), style=row_style or "#d8dee9")
            shortcut = getattr(cmd, "shortcut", None)
            if shortcut:
                out.append(f"  {shortcut}", style="#6f778a italic")
            if i == start and start > 0:
                out.append(f"  ↑ {start}", style="#6f778a")
            if i == end - 1 and end < len(self.visible_commands):
                out.append(f"  ↓ {len(self.visible_commands) - end}", style="#6f778a")
            if i < end - 1:
                out.append("\n")
        self.update(out)

    def _render_window(self, selected: int) -> tuple[int, int]:
        total = len(self.visible_commands)
        limit = self.MAX_RENDERED_ROWS
        if total <= limit:
            return 0, total
        half = limit // 2
        start = max(0, selected - half)
        start = min(start, total - limit)
        return start, start + limit


class PathMentionMenu(Static):
    """Popup path completer for prompt tokens that start with ``@``."""

    DEFAULT_CSS = """
    PathMentionMenu {
        dock: bottom;
        height: auto;
        max-height: 12;
        padding: 0 1;
        background: #1d2130;
        color: #d8dee9;
        display: none;
        border-top: solid #7aa2f7;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
    }
    PathMentionMenu.has-items {
        display: block;
    }
    """

    selected_index: reactive[int] = reactive(0)
    visible_items: reactive[tuple[PathMentionItem, ...]] = reactive(())

    def __init__(self) -> None:
        super().__init__("")
        self._workspace_root = Path.cwd()

    def set_workspace_root(self, root: Path) -> None:
        self._workspace_root = root

    def update_query(self, token: str) -> None:
        if not token.startswith("@"):
            self._hide()
            return
        raw_path = token[1:]
        if not raw_path or any(ch.isspace() for ch in raw_path):
            self._show_candidates("", "")
            return
        if raw_path.startswith(("/", "~")) or ".." in Path(raw_path).parts:
            self._hide()
            return
        if "/" in raw_path:
            parent_text, prefix = raw_path.rsplit("/", 1)
        else:
            parent_text, prefix = "", raw_path
        self._show_candidates(parent_text, prefix)

    def _show_candidates(self, parent_text: str, prefix: str) -> None:
        parent = (self._workspace_root / parent_text).resolve()
        try:
            parent.relative_to(self._workspace_root.resolve())
        except ValueError:
            self._hide()
            return
        if not parent.is_dir():
            self._hide()
            return

        items: list[PathMentionItem] = []
        try:
            children = list(parent.iterdir())
        except OSError:
            self._hide()
            return

        for child in children:
            name = child.name
            if name in _IGNORED_PATH_NAMES:
                continue
            if name.startswith(".") and not prefix.startswith("."):
                continue
            if prefix and not name.lower().startswith(prefix.lower()):
                continue
            is_dir = child.is_dir()
            display = f"{parent_text}/{name}" if parent_text else name
            if is_dir:
                display += "/"
            items.append(PathMentionItem(display=display, path=child, is_dir=is_dir))

        items.sort(key=lambda item: (not item.is_dir, item.display.lower()))
        self.visible_items = tuple(items[:80])
        if not self.visible_items:
            self._hide()
            return
        self.selected_index = min(self.selected_index, len(self.visible_items) - 1)
        self.add_class("has-items")
        self._repaint()

    def _hide(self) -> None:
        self.visible_items = ()
        self.selected_index = 0
        self.remove_class("has-items")
        self.update("")

    def watch_visible_items(self, _value: tuple[PathMentionItem, ...]) -> None:
        self._repaint()

    def watch_selected_index(self, _value: int) -> None:
        if self.visible_items:
            self._repaint()

    def move_up(self) -> None:
        if not self.visible_items:
            return
        self.selected_index = (self.selected_index - 1) % len(self.visible_items)

    def move_down(self) -> None:
        if not self.visible_items:
            return
        self.selected_index = (self.selected_index + 1) % len(self.visible_items)

    @property
    def selected_item(self) -> PathMentionItem | None:
        if not self.visible_items:
            return None
        return self.visible_items[self.selected_index % len(self.visible_items)]

    @property
    def is_open(self) -> bool:
        return bool(self.visible_items)

    def _repaint(self) -> None:
        if not self.visible_items:
            self.update("")
            return
        out = Text()
        for i, item in enumerate(self.visible_items):
            is_sel = i == self.selected_index % len(self.visible_items)
            prefix = "▸ " if is_sel else "  "
            out.append(prefix, style="bold #7aa2f7" if is_sel else "#6f778a")
            out.append(
                pad_cells(f"@{item.display}", 52),
                style="bold #89ddff" if is_sel else "#aeb6c8",
            )
            out.append("dir" if item.is_dir else "file", style="#6f778a")
            if i < len(self.visible_items) - 1:
                out.append("\n")
        self.update(out)


class StatusBar(Static):
    """A 1-line status strip docked just above the input.

    Doubles as the visible separator between the scrollable history above
    and the input box below — so it's always visible. Content depends on
    agent state:

      * idle     →  ─────────────── ready ───────────────
      * thinking →  ─── ⠼ thinking · 2.3s ─────── esc cancel
      * waiting  →  ─── ⠼ waiting · next tool · 2.3s ─ esc cancel
      * tool     →  ─── ⠼ Bash · which psql · 1.4s ─── esc cancel
      * text     →  ─── ⠼ generating · 5.1s ──────── esc cancel
    """

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: #171a23;
        color: #d8dee9;
    }
    StatusBar.idle {
        background: #11131a;
        color: #6f778a;
    }
    """

    state: reactive[str] = reactive("idle")  # idle | thinking | waiting | tool | text
    detail: reactive[str] = reactive("")
    started_at: reactive[float] = reactive(0.0)
    spinner_frame: reactive[int] = reactive(0)
    context_pct: reactive[float] = reactive(0.0)

    def on_mount(self) -> None:
        self._sync_class()
        self._repaint()
        # 10 Hz tick for spinner + duration
        self.set_interval(1.0 / 10.0, self._tick)

    def on_resize(self, _event: Any) -> None:
        self._repaint()

    def _tick(self) -> None:
        if self.state != "idle":
            self.spinner_frame = (self.spinner_frame + 1) % len(SPINNER_FRAMES)
            self._repaint()

    def watch_state(self, value: str) -> None:
        if value == "idle":
            self.started_at = 0.0
        else:
            self.started_at = time.monotonic()
        self._sync_class()
        self._repaint()

    def watch_detail(self, _value: str) -> None:
        self._repaint()

    def watch_context_pct(self, _value: float) -> None:
        self._repaint()

    def _sync_class(self) -> None:
        if self.state == "idle":
            self.add_class("idle")
        else:
            self.remove_class("idle")

    def set_status(self, state: str, detail: str = "") -> None:
        """Convenience setter for app code: ``status.set_status('thinking')``."""
        self.detail = detail
        self.state = state

    @classmethod
    def label_for_state(cls, state: str) -> str:
        labels = {
            "idle": "ready",
            "thinking": "thinking",
            "waiting": "waiting for tool result",
            "tool": "running tool",
            "text": "streaming response",
        }
        return labels.get(state, state)

    def _label(self) -> str:
        return self.label_for_state(self.state)

    @classmethod
    def context_style_for_pct(cls, pct: float) -> str:
        if pct > 85:
            return "#f7768e"
        if pct >= 70:
            return "#e0af68"
        return "#6f778a"

    def _context_text(self) -> Text:
        pct = max(0.0, float(self.context_pct or 0.0))
        if pct <= 0:
            return Text()
        out = Text(f"{pct:.0f}% ctx", style=self.context_style_for_pct(pct))
        if pct > 85:
            out.append(" · compact soon", style="#f7768e")
        return out

    def _status_label(self, label: str, *, base_style: str) -> Text:
        out = Text(label, style=base_style)
        ctx = self._context_text()
        if ctx.plain:
            out.append(" · ", style="#6f778a")
            out.append_text(ctx)
        return out

    def _repaint(self) -> None:
        width = max(20, self.size.width or 80)
        text = Text()
        if self.state == "idle":
            label = self._status_label("ready", base_style="#6f778a")
            label.pad_left(1)
            label.pad_right(1)
            dash_total = max(0, width - label.cell_len - 2)
            left = dash_total // 2
            right = dash_total - left
            text.append("─" * left, style="#3b4252")
            text.append_text(label)
            text.append("─" * right, style="#3b4252")
        else:
            spin = SPINNER_FRAMES[self.spinner_frame % len(SPINNER_FRAMES)]
            label = self._label()
            elapsed = max(0.0, time.monotonic() - self.started_at) if self.started_at else 0.0
            hint = " esc cancel "
            style = {
                "thinking": "#e0af68",
                "waiting": "#e0af68",
                "tool": "#7dcfff",
                "text": "#7dcfff",
            }.get(self.state, "#7dcfff")
            middle = Text(f" {spin} ", style=style)
            status_label = self._status_label(label, base_style=style)
            middle.append_text(status_label)
            if self.detail:
                middle.append(" · ", style="#6f778a")
                middle.append(self.detail, style=style)
            middle.append(f" · {elapsed:.1f}s ", style=style)
            dash_total = max(0, width - middle.cell_len - cell_len(hint) - 2)
            left = max(2, dash_total // 2)
            right = max(2, dash_total - left)
            text.append("─" * left, style="#3b4252")
            text.append_text(middle)
            text.append("─" * right, style="#3b4252")
            text.append(hint, style="#6f778a")
        self.update(text)


class LivePane(Static):
    """Mutable region above the input that animates spinners + streaming text.

    Owns 0..N "live blocks" (streaming text, in-flight tool calls, thinking).
    Each block has a ``render(width, frame)`` → RenderableType callback.
    The pane re-renders at ~10fps via set_interval so spinners cycle.

    When a block finalizes, the app calls ``commit(block_id)`` which removes
    it here and appends its final state to the RichLog history.
    """

    DEFAULT_CSS = """
    LivePane {
        dock: bottom;
        height: auto;
        max-height: 30;
        padding: 0 1;
        background: #11131a;
        color: #d8dee9;
    }
    LivePane.empty {
        display: none;
    }
    """

    REFRESH_HZ: float = 10.0

    def __init__(self) -> None:
        super().__init__("")
        # block_id -> render callable; insertion order preserved
        self._blocks: dict[str, Callable[[int, int], RenderableType]] = {}
        self._frame: int = 0
        self._interval = None
        self.add_class("empty")

    def on_mount(self) -> None:
        self._interval = self.set_interval(1.0 / self.REFRESH_HZ, self._tick)

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % 1_000_000
        if self._blocks:
            self._repaint()

    @property
    def has_blocks(self) -> bool:
        return bool(self._blocks)

    def attach(self, block_id: str, renderer: Callable[[int, int], RenderableType]) -> None:
        """Add (or replace) a live block. ``renderer(width, frame)`` returns Rich."""
        self._blocks[block_id] = renderer
        self.remove_class("empty")
        self._repaint()

    def detach(self, block_id: str) -> None:
        """Remove a live block (already committed to history elsewhere)."""
        self._blocks.pop(block_id, None)
        if not self._blocks:
            self.add_class("empty")
            self.update(Text(""))
            return
        self._repaint()

    def clear_all(self) -> None:
        self._blocks.clear()
        self.add_class("empty")
        self.update(Text(""))

    def _repaint(self) -> None:
        if not self._blocks:
            self.update(Text(""))
            return
        width = max(40, self.size.width or 100)
        renderables: list[RenderableType] = []
        for renderer in self._blocks.values():
            try:
                renderables.append(renderer(width, self._frame))
            except Exception:
                # A bad renderer shouldn't crash the whole live pane.
                renderables.append(Text("(render error)", style="red"))
        group = Group(*renderables)
        self.update(_render_themed(group, width=width))


class PromptArea(TextArea):
    """Multiline prompt input — grows up to ``MAX_LINES`` rows.

    Uses ``TextArea`` (not ``Input``) so we can support newlines and dynamic
    height. Enter submits; Alt+Enter / Ctrl+J / Shift+Enter inserts a
    newline. The ``Submitted`` message is fired manually since TextArea
    doesn't have a built-in submit event.
    """

    DEFAULT_CSS = """
    PromptArea {
        dock: bottom;
        height: auto;
        min-height: 3;
        max-height: 10;
        border: none;
        padding: 0 1;
        background: #171a23;
        color: #d8dee9;
        scrollbar-size-vertical: 0;
    }
    PromptArea:focus {
        border: none;
    }
    PromptArea > .text-area--cursor {
        background: #7aa2f7;
    }
    """

    BINDINGS: ClassVar = [
        # newline: alt+enter, ctrl+j, shift+enter
        ("alt+enter", "newline", "Newline"),
        ("ctrl+j", "newline", "Newline"),
        ("shift+enter", "newline", "Newline"),
    ]

    class Submitted(TextArea.Changed):
        """Posted when the user presses Enter to submit."""

        def __init__(self, text_area: TextArea, value: str) -> None:
            super().__init__(text_area)
            self.value: str = value

    def __init__(self) -> None:
        super().__init__(
            text="",
            id="prompt-input",
            language=None,
            theme="css",
            soft_wrap=True,
            show_line_numbers=False,
            tab_behavior="focus",
            compact=True,
            placeholder=("Message… Enter sends · Shift+Enter newline · / commands · @ files"),
        )
        self._terminal_associated_text_buffer = ""

    def on_mount(self) -> None:
        # No placeholder API on TextArea, so we leave it blank;
        # ``HeaderBar`` already gives the user a visible greeting.
        self.show_vertical_scrollbar = False

    def normalize_terminal_input(self) -> bool:
        """Return True when raw terminal protocol text was normalized."""
        normalized = decode_terminal_associated_text(self.text)
        if normalized == self.text:
            return False
        self.text = normalized
        lines = normalized.split("\n")
        self.move_cursor((len(lines) - 1, len(lines[-1])), select=False)
        return True

    def _arm_terminal_associated_text_flush(self) -> None:
        expected = self._terminal_associated_text_buffer
        self.set_timer(
            _TERMINAL_ASSOCIATED_TEXT_FLUSH_DELAY,
            lambda: self._flush_terminal_associated_text_buffer(expected),
        )

    def _flush_terminal_associated_text_buffer(self, expected: str | None = None) -> None:
        if expected is not None and self._terminal_associated_text_buffer != expected:
            return
        buffered = self._terminal_associated_text_buffer
        self._terminal_associated_text_buffer = ""
        if buffered:
            self.insert(buffered)

    def _consume_terminal_associated_text_key(self, event: Any) -> bool:
        character = getattr(event, "character", None)
        if not isinstance(character, str) or len(character) != 1:
            self._flush_terminal_associated_text_buffer()
            return False

        if self._terminal_associated_text_buffer:
            candidate = self._terminal_associated_text_buffer + character
            if _is_terminal_associated_text_prefix(candidate):
                event.stop()
                event.prevent_default()
                self._terminal_associated_text_buffer = candidate
                if _TERMINAL_ASSOCIATED_TEXT_EXACT_RE.fullmatch(candidate):
                    self._terminal_associated_text_buffer = ""
                    self.insert(decode_terminal_associated_text(candidate))
                else:
                    self._arm_terminal_associated_text_flush()
                return True

            buffered = self._terminal_associated_text_buffer
            self._terminal_associated_text_buffer = ""
            self.insert(buffered + character)
            event.stop()
            event.prevent_default()
            return True

        if character in {"[", "^"}:
            event.stop()
            event.prevent_default()
            self._terminal_associated_text_buffer = character
            self._arm_terminal_associated_text_flush()
            return True
        return False

    def action_newline(self) -> None:
        self.insert("\n")

    async def _on_key(self, event: Any) -> None:  # type: ignore[override]
        if self._consume_terminal_associated_text_key(event):
            return
        # Intercept plain Enter as submit; TextArea normally inserts newline.
        if event.key == "enter":
            value = self.text
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self, value))
            return
        await super()._on_key(event)


class ConsoleBody(Container):
    """Wrapper container for the scrollable log + steering pane."""

    DEFAULT_CSS = """
    ConsoleBody {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        # Children appended dynamically by the app.
        yield from ()
