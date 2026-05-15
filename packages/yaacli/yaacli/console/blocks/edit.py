"""Edit / multi-edit block — file diff inside a panel under the ⏺ anchor."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from yaacli.console.blocks.base import BaseBlock, BlockKind
from yaacli.console.design import tail_truncate_cells, timeline_line
from yaacli.console.glyphs import GLYPHS

_MAX_DIFF_DISPLAY_LINES = 80


@dataclass(frozen=True)
class _DiffHunk:
    header: str
    lines: tuple[str, ...]
    additions: int
    deletions: int


def _diff_lines(old: str, new: str, *, context: int = 3) -> tuple[list[str], int, int]:
    """Return (rendered_lines, additions, deletions)."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = difflib.unified_diff(old_lines, new_lines, n=context, lineterm="")
    additions = 0
    deletions = 0
    out: list[str] = []
    for line in diff:
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
        out.append(line)
    return out, additions, deletions


def _split_hunks(lines: list[str]) -> list[_DiffHunk]:
    hunks: list[_DiffHunk] = []
    header = ""
    body: list[str] = []
    additions = 0
    deletions = 0

    def flush() -> None:
        nonlocal additions, body, deletions, header
        if not header and not body:
            return
        hunks.append(_DiffHunk(
            header=header or "@@",
            lines=tuple(body),
            additions=additions,
            deletions=deletions,
        ))
        header = ""
        body = []
        additions = 0
        deletions = 0

    for line in lines:
        if line.startswith("@@"):
            flush()
            header = line
            body = [line]
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
        body.append(line)
    flush()
    return hunks


def _short_path(path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(Path.cwd()))
    except ValueError:
        return str(p)


@dataclass
class EditBlock(BaseBlock):
    """A single file edit. ``edits`` may contain multiple hunks."""

    path: str = ""
    edits: list[tuple[str, str]] = field(default_factory=list)  # (old, new)
    expanded: bool = True

    def __post_init__(self) -> None:
        self.kind = BlockKind.EDIT
        super().__post_init__()
        self.state.is_terminal = True

    @classmethod
    def single(cls, path: str, old_string: str, new_string: str) -> EditBlock:
        return cls(path=path, edits=[(old_string, new_string)])

    def toggle_expanded(self) -> None:
        self.expanded = not self.expanded

    def summary_text(self) -> str:
        total_add = 0
        total_del = 0
        total_hunks = 0
        for old, new in self.edits:
            lines, adds, dels = _diff_lines(old, new)
            total_add += adds
            total_del += dels
            total_hunks += len(_split_hunks(lines))
        noun = "hunk" if total_hunks == 1 else "hunks"
        return f"{_short_path(self.path)} · {total_hunks} {noun} · +{total_add} −{total_del}"

    def render(self, width: int) -> RenderableType:
        all_lines: list[str] = []
        total_add = 0
        total_del = 0
        total_hunks = 0
        for i, (old, new) in enumerate(self.edits):
            if i > 0:
                all_lines.append("")
            lines, adds, dels = _diff_lines(old, new)
            hunks = _split_hunks(lines)
            total_hunks += len(hunks)
            if self.expanded:
                all_lines.extend(lines)
            else:
                for hunk in hunks:
                    all_lines.append(
                        f"{hunk.header} · +{hunk.additions} −{hunk.deletions}"
                    )
            total_add += adds
            total_del += dels

        noun = "hunk" if total_hunks == 1 else "hunks"
        header = timeline_line(
            label="Edit",
            status="done",
            meta=[f"{total_hunks} {noun}", f"+{total_add}", f"−{total_del}"],
            summary=tail_truncate_cells(_short_path(self.path), 72),
            marker=GLYPHS.CHECK,
            label_style="console.tool.name",
            status_style="console.state.success",
        )

        hidden_count = max(0, len(all_lines) - _MAX_DIFF_DISPLAY_LINES)
        display_lines = all_lines[:_MAX_DIFF_DISPLAY_LINES]

        body = Text()
        for line in display_lines or ["no changes"]:
            if line.startswith("@@") or " · +" in line:
                body.append(line + "\n", style="console.diff.meta")
            elif line.startswith("+"):
                body.append(line + "\n", style="console.diff.add")
            elif line.startswith("-"):
                body.append(line + "\n", style="console.diff.del")
            else:
                body.append(line + "\n", style="console.diff.context")
        if hidden_count:
            body.append(f"… {hidden_count} diff lines hidden\n", style="console.diff.meta")

        title = Text()
        title.append("+", style="console.diff.add")
        title.append(f"{total_add}", style="console.diff.add")
        title.append("  ", style="console.diff.meta")
        title.append("−", style="console.diff.del")  # MINUS SIGN
        title.append(f"{total_del}", style="console.diff.del")

        # Subtract a couple of cells for the panel borders
        panel_width = max(40, min(width - 2, 120))
        panel = Panel(
            body,
            title=title,
            title_align="left",
            border_style="dim",
            padding=(0, 1),
            width=panel_width,
        )
        return Group(header, panel)
