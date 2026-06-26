"""UI-independent service interfaces used by desktop adapters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from yaacli.desktop.protocol import ApprovalDecision, EventEnvelope, InputPart, SessionSnapshot, SessionSummary

EventSink = Callable[[EventEnvelope], Awaitable[None]]


class DesktopRuntimeError(RuntimeError):
    """Typed service error converted into a protocol error by the sidecar."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class DesktopRuntimeApi(Protocol):
    """Operations a desktop presentation may request from YAACLI."""

    async def open_workspace(self, path: str) -> dict[str, Any]: ...

    async def create_session(self, name: str = "") -> SessionSnapshot: ...

    async def list_sessions(self) -> list[SessionSummary]: ...

    async def load_session(self, session_id: str) -> SessionSnapshot: ...

    async def rename_session(self, session_id: str, name: str) -> SessionSummary: ...

    async def archive_session(self, session_id: str) -> None: ...

    async def start_run(self, session_id: str, input_parts: list[InputPart]) -> str: ...

    async def cancel_run(self, run_id: str) -> None: ...

    async def steer_run(self, run_id: str, text: str) -> None: ...

    async def resolve_approval(
        self,
        approval_id: str,
        workspace_id: str,
        session_id: str,
        run_id: str,
        decision: ApprovalDecision,
        reason: str | None = None,
    ) -> None: ...

    async def close(self) -> None: ...
