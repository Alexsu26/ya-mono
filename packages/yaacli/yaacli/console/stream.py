"""LiveStream — owns the single mutable tail region of the console.

Append-only history is achieved by keeping every active block in
``_tail`` (rendered together via rich.live.Live) and ``console.print``-ing
each block as it transitions to the terminal state.

Core invariant: only LiveStream writes to the terminal during a turn.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from rich.console import Console, Group, RenderableType
from rich.live import Live

from yaacli.console.blocks.base import Block

_REFRESH_PER_SECOND = 12


class LiveStream:
    """Mutable tail + immutable history scroller."""

    def __init__(self, console: Console, *, refresh_per_second: int = _REFRESH_PER_SECOND) -> None:
        self._console = console
        self._refresh_per_second = refresh_per_second
        self._tail: list[Block] = []
        self._live: Live | None = None
        self._started_at: float = 0.0

    @property
    def console(self) -> Console:
        return self._console

    @property
    def is_open(self) -> bool:
        return self._live is not None

    def open(self) -> None:
        """Start the Live region. No-op if already open."""
        if self._live is not None:
            return
        self._tail.clear()
        self._started_at = time.monotonic()
        self._live = Live(
            self._render_tail(),
            console=self._console,
            refresh_per_second=self._refresh_per_second,
            transient=False,
            auto_refresh=True,
            redirect_stderr=False,
            redirect_stdout=False,
        )
        self._live.start()

    def close(self) -> None:
        """Commit any remaining tail blocks to history and stop the Live."""
        if self._live is None:
            return
        # Promote anything still alive to history. Anything finalized first.
        for block in self._tail:
            if not block.is_terminal():
                block.state.is_terminal = True
        self._flush_tail(force_all=True)
        # Live.stop() leaves the final renderable on screen — but we already
        # printed everything, so swap to an empty group first.
        self._live.update(Group(), refresh=False)
        self._live.stop()
        self._live = None
        self._tail.clear()

    @contextmanager
    def session(self) -> Iterator[LiveStream]:
        """Convenience: ``with stream.session(): ...`` opens/closes the Live."""
        self.open()
        try:
            yield self
        finally:
            self.close()

    def attach(self, block: Block) -> None:
        """Add a block to the tail."""
        self._tail.append(block)
        self._refresh()

    def update(self, block: Block) -> None:
        """Mark a block dirty. (No-op other than triggering a refresh.)"""
        # If the block isn't in our tail (e.g., already committed), ignore.
        if block in self._tail:
            self._refresh()

    def commit(self, block: Block) -> None:
        """Move a block from tail to history immediately."""
        if block not in self._tail:
            return
        block.state.is_terminal = True
        self._flush_tail()

    def print(self, block: Block) -> None:
        """Print a self-contained block directly to history.

        Use for blocks that never have a streaming form (user prompts,
        breadcrumbs). The block is rendered once and immediately scrolled.
        """
        if self._live is not None:
            # While Live is active, the renderer queues prints below the tail.
            # Commit the queued prints by rendering through Live's console.
            self._live.console.print(block.render(self._tty_width()))
        else:
            self._console.print(block.render(self._tty_width()))

    def breadcrumb(self, text: str, *, style: str = "console.breadcrumb") -> None:
        """One-line marker straight to history without going through a block."""
        if self._live is not None:
            self._live.console.print(text, style=style)
        else:
            self._console.print(text, style=style)

    # -------- internal helpers -------------------------------------------------

    def _tty_width(self) -> int:
        size = self._console.size
        return max(40, size.width)

    def _render_tail(self) -> RenderableType:
        if not self._tail:
            return Group()
        width = self._tty_width()
        return Group(*[b.render(width) for b in self._tail])

    def _refresh(self) -> None:
        if self._live is None:
            return
        # Flush any newly-finalized blocks before re-rendering the live tail
        self._flush_tail()
        self._live.update(self._render_tail(), refresh=False)

    def _flush_tail(self, *, force_all: bool = False) -> None:
        """Move all leading-finalized blocks from tail to history.

        This preserves order: a finalized block stuck behind a still-running
        sibling stays in the tail until everything ahead of it commits.
        """
        if not self._tail or self._live is None:
            return

        # Identify leading prefix of finalized blocks.
        cut = 0
        for block in self._tail:
            if block.is_terminal() or force_all:
                cut += 1
            else:
                break

        if cut == 0:
            return

        committed = self._tail[:cut]
        self._tail = self._tail[cut:]

        width = self._tty_width()
        # Update Live to drop the committed blocks before printing them so
        # they don't double-render.
        self._live.update(self._render_tail(), refresh=False)
        for block in committed:
            self._live.console.print(block.render(width))
