"""Transcript-first visual helpers for the Textual console.

Unified block system
--------------------
Every block renders as a 2-column layout so their left edges align:

    ● LABEL  meta
      body line one
      body line two

* Column 0 (gutter): a single coloured status dot + one space (2 cells wide).
* Column 1: the LABEL (uppercase, coloured) on the header row; body lines are
  indented by the same 2 cells so everything lines up under the label.

Only the dot and the label carry the block's semantic colour — body text stays
neutral. This keeps the transcript calm and lets the eye scan block boundaries
by the coloured dots alone.
"""

from __future__ import annotations

from collections.abc import Iterable

from rich.cells import cell_len, set_cell_size
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.text import Text

# Shared gutter width for every block (dot + space, or two-space body indent).
GUTTER = "  "
GUTTER_WIDTH = 2


def truncate_cells(value: object, width: int, *, ellipsis: str = "…") -> str:
    """Trim text to a terminal cell width without splitting wide characters."""
    text = str(value)
    if width <= 0:
        return ""
    if cell_len(text) <= width:
        return text
    if width <= cell_len(ellipsis):
        return set_cell_size(ellipsis, width).rstrip()
    return set_cell_size(text, width - cell_len(ellipsis)).rstrip() + ellipsis


def tail_truncate_cells(value: object, width: int, *, ellipsis: str = "…") -> str:
    """Trim from the left, preserving the right side of a path/command."""
    text = str(value)
    if width <= 0:
        return ""
    if cell_len(text) <= width:
        return text
    if width <= cell_len(ellipsis):
        return set_cell_size(ellipsis, width).rstrip()
    budget = width - cell_len(ellipsis)
    kept = ""
    for char in reversed(text):
        candidate = char + kept
        if cell_len(candidate) > budget:
            break
        kept = candidate
    return ellipsis + kept


def pad_cells(value: object, width: int) -> str:
    """CJK-safe left-aligned padding for compact terminal tables."""
    text = truncate_cells(value, width)
    return text + (" " * max(0, width - cell_len(text)))


def compact_meta(parts: Iterable[object]) -> str:
    """Join non-empty metadata parts with the TUI's compact separator."""
    return "  ".join(str(part) for part in parts if str(part or "").strip())


def block_header(
    dot: str,
    label: str,
    *,
    meta: str = "",
    dot_style: str,
    label_style: str,
) -> Text:
    """The header row of a unified block: ``● LABEL  meta``.

    The dot occupies column 0; the label starts at the same column every
    block's body content will indent to (GUTTER_WIDTH).
    """
    out = Text()
    out.append(f"{dot} ", style=dot_style)
    out.append(label.upper(), style=label_style)
    if meta:
        out.append("  ", style="console.meta")
        out.append(meta, style="console.meta")
    return out


def block_body_text(value: object, *, body_style: str = "console.text.primary") -> Text:
    """Render plain text indented under the unified block gutter."""
    lines = str(value or "").splitlines() or [""]
    out = Text()
    for index, line in enumerate(lines):
        if index:
            out.append("\n")
        out.append(GUTTER)
        out.append(line, style=body_style)
    return out


def block_body_renderable(renderable: RenderableType) -> RenderableType:
    """Indent a Rich renderable under the unified block gutter."""
    return Padding(renderable, (0, 0, 0, GUTTER_WIDTH))


def turn_header(
    glyph: str,
    label: str,
    *,
    meta: str = "",
    glyph_style: str = "console.accent.assistant",
    label_style: str = "console.heading.turn",
) -> Text:
    out = Text()
    out.append(f"{glyph} ", style=glyph_style)
    out.append(label, style=label_style)
    if meta:
        out.append("  ", style="console.meta")
        out.append(meta, style="console.meta")
    return out


def rail_text(
    value: object,
    *,
    rail: str = "  │ ",
    rail_style: str = "console.border.subtle",
    body_style: str = "console.text.primary",
) -> Text:
    """Render plain text under a transcript rail."""
    lines = str(value or "").splitlines() or [""]
    out = Text()
    for index, line in enumerate(lines):
        if index:
            out.append("\n")
        out.append(rail, style=rail_style)
        out.append(line, style=body_style)
    return out


def rail_renderable(renderable: RenderableType) -> RenderableType:
    """Indent a Rich renderable under a subtle transcript rail."""
    return Group(
        Text("  │", style="console.border.subtle"),
        Padding(renderable, (0, 0, 0, 4)),
    )


def timeline_line(
    *,
    branch: str = "├─",  # retained for API compat; no longer rendered
    label: str,
    status: str = "",
    meta: Iterable[object] = (),
    summary: str = "",
    marker: str = "",
    label_style: str = "console.heading.block",
    status_style: str = "console.meta",
) -> Text:
    """One tool-call row, aligned to the unified block gutter.

    Renders as ``<marker> LABEL  status  meta  summary`` where ``<marker>`` (a
    status dot or spinner frame) sits in column 0, matching every other block's
    dot. The old ``├─`` tree branch is dropped so tool calls align with user /
    assistant / thinking blocks instead of sitting in their own indent.
    """
    out = Text()
    out.append(f"{marker or ' '} ", style=status_style)
    out.append(label, style=label_style)
    if status:
        out.append("  ", style="console.meta")
        out.append(status, style=status_style)
    meta_text = compact_meta(meta)
    if meta_text:
        out.append("  ", style="console.meta")
        out.append(meta_text, style="console.meta")
    if summary:
        out.append("  ", style="console.meta")
        out.append(summary, style="console.text.secondary")
    return out
