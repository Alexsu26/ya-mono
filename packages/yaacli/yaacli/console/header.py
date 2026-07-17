"""Header and footer hint renderers.

The header is printed once per session (and once after /clear).
The footer hint appears immediately above the prompt at every turn boundary.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rich.console import RenderableType
from rich.text import Text

from yaacli.console.design import truncate_cells


@dataclass
class HeaderInfo:
    cwd: Path
    branch: str | None
    dirty: bool
    model: str | None
    context_pct: float | None
    cost_str: str | None

    @classmethod
    def gather(cls, cwd: Path, model: str | None) -> HeaderInfo:
        branch, dirty = _git_state(cwd)
        return cls(
            cwd=cwd,
            branch=branch,
            dirty=dirty,
            model=model,
            context_pct=None,
            cost_str=None,
        )


def _git_state(cwd: Path) -> tuple[str | None, bool]:
    if not shutil.which("git"):
        return None, False
    try:
        branch = subprocess.run(  # noqa: S603
            ["git", "-C", str(cwd), "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if branch.returncode != 0:
            return None, False
        status = subprocess.run(  # noqa: S603
            ["git", "-C", str(cwd), "status", "--porcelain"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return branch.stdout.strip() or None, bool(status.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return None, False


_DIV = "  │  "


def _mini_bar(pct: float, *, cells: int = 8) -> str:
    """A tiny unicode progress bar for context usage."""
    pct = max(0.0, min(100.0, pct))
    filled = round(pct / 100 * cells)
    return "█" * filled + "░" * (cells - filled)


def render_header(info: HeaderInfo, *, width: int = 0) -> RenderableType:
    """Segmented status line: path │ ⑂ branch │ ◆ model … [ctx bar] pct · cost.

    The left cluster (path / branch / model) is separated by dim ``│`` rules;
    the right cluster (context bar + cost) is padded flush to the right edge
    when a width is supplied.
    """
    left = Text()
    left.append(truncate_cells(_pretty_cwd(info.cwd), 40), style="console.header.path")
    if info.branch:
        left.append(_DIV, style="console.header.divider")
        left.append("⑂ ", style="console.header.icon")
        left.append(truncate_cells(info.branch, 20), style="console.header.branch")
        if info.dirty:
            left.append(" •", style="console.header.dirty")
    if info.model:
        left.append(_DIV, style="console.header.divider")
        left.append("◆ ", style="console.header.icon")
        left.append(truncate_cells(info.model, 34), style="console.header.model")

    right = Text()
    if info.context_pct is not None:
        style = "console.header.ctx"
        if info.context_pct > 85:
            style = "console.state.error"
        elif info.context_pct >= 70:
            style = "console.state.warning"
        right.append(_mini_bar(info.context_pct), style=style)
        right.append(f" {info.context_pct:.0f}%", style="console.header.cost")
    if info.cost_str:
        if info.context_pct is not None:
            right.append("  ·  ", style="console.header.divider")
        right.append(info.cost_str, style="console.header.cost")

    if width <= 0 or not right.plain:
        if right.plain:
            left.append(_DIV, style="console.header.divider")
            left.append_text(right)
        return left

    gap = width - left.cell_len - right.cell_len
    if gap < 2:
        # Not enough room — drop the right cluster onto the same line tightly.
        left.append("  ", style="console.header.divider")
        left.append_text(right)
        return left
    left.append(" " * gap)
    left.append_text(right)
    return left


def _pretty_cwd(path: Path) -> str:
    home = Path.home()
    try:
        rel = path.relative_to(home)
        return f"~/{rel}" if str(rel) != "." else "~"
    except ValueError:
        return str(path)


def render_footer_hint(*, mode: str, ready: bool) -> RenderableType:
    out = Text()
    out.append(" ↵ send", style="console.footer.hint")
    out.append("  ·  ", style="console.footer.hint")
    out.append("⌥↵ newline", style="console.footer.hint")
    out.append("  ·  ", style="console.footer.hint")
    out.append("/ commands", style="console.footer.hint")
    out.append("  ·  ", style="console.footer.hint")
    out.append("ctrl-c cancel", style="console.footer.hint")

    out.append("        ", style="console.footer.hint")
    mode_style = "console.mode.act" if mode.lower() == "act" else "console.mode.plan"
    out.append(mode.upper(), style=mode_style)
    out.append(" · ", style="console.footer.hint")
    if ready:
        out.append("ready", style="console.footer.ready")
    else:
        out.append("working", style="console.footer.working")
    return out
