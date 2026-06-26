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


def render_header(info: HeaderInfo) -> RenderableType:
    line1 = Text()
    line1.append(truncate_cells(_pretty_cwd(info.cwd), 38), style="console.header.path")
    if info.branch:
        line1.append("  git ", style="console.header.branch")
        line1.append(truncate_cells(info.branch, 18), style="console.header.branch")
        line1.append(
            "*" if info.dirty else "",
            style="console.header.dirty" if info.dirty else "console.header.branch",
        )
    if info.model:
        line1.append("  model ", style="console.header.branch")
        line1.append(truncate_cells(info.model, 34), style="console.header.model")

    if info.context_pct is not None or info.cost_str:
        line2 = Text()
        if info.context_pct is not None:
            line2.append(f"{info.context_pct:.0f}% used", style="console.header.cost")
        if info.cost_str:
            if info.context_pct is not None:
                line2.append(" · ", style="console.header.cost")
            line2.append(info.cost_str, style="console.header.cost")
        return Text("\n").join([line1, line2])
    return line1


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
