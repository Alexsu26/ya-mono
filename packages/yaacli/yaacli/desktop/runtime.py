"""Desktop-facing runtime service built on the shared YAACLI execution path."""

from __future__ import annotations

import asyncio
import base64
import binascii
import difflib
import hashlib
import json
import os
import re
import shutil
import uuid
from contextlib import AsyncExitStack, suppress
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, cast

from pydantic_ai import BinaryContent, DeferredToolRequests, DeferredToolResults, ToolDenied
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)
from ya_agent_sdk.events import FileChangeEvent, ModelRequestStartEvent, TaskEvent, ToolCallsStartEvent

from yaacli.config import ConfigManager, YaacliConfig
from yaacli.console.theme import THEME_NAMES
from yaacli.console.transcript import TranscriptStore, new_session_id
from yaacli.desktop.api import DesktopRuntimeError, EventSink
from yaacli.desktop.protocol import (
    ApprovalDecision,
    ApprovalRequest,
    EventEnvelope,
    FileChange,
    InputPart,
    InputPartType,
    RunInfo,
    RunStatus,
    SessionSnapshot,
    SessionSummary,
    UsageInfo,
    WorkspaceInfo,
)
from yaacli.events import ContextUpdateEvent
from yaacli.execution import open_runtime_stream
from yaacli.logging import get_logger
from yaacli.model_profiles import (
    build_model_profiles,
    get_model_profile,
    get_startup_model_profile,
    save_selected_model_profile_id,
)
from yaacli.runtime import create_tui_runtime

logger = get_logger(__name__)

_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
_TOKEN_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*|\bsk-[A-Za-z0-9_-]{12,}\b")
_GIT_HEAD_PREFIX = "ref: refs/heads/"


def _read_git_branch(path: Path) -> str | None:
    """Best-effort current branch from ``.git/HEAD`` (no subprocess).

    Returns ``None`` for non-repos, detached HEAD, or worktree ``.git`` files.
    """
    head = path / ".git" / "HEAD"
    try:
        line = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if line.startswith(_GIT_HEAD_PREFIX):
        branch = line[len(_GIT_HEAD_PREFIX) :]
        return branch or None
    return None


class DesktopRuntimeService:
    """Own one workspace-scoped YAACLI runtime and its desktop sessions."""

    def __init__(self, event_sink: EventSink, *, config_dir: Path | None = None) -> None:
        self._event_sink = event_sink
        self._config_dir = config_dir
        self._workspace: WorkspaceInfo | None = None
        self._workspace_path: Path | None = None
        self._config_manager: ConfigManager | None = None
        self._config: YaacliConfig | None = None
        self._active_profile_name: str | None = None
        self._runtime: Any = None
        self._runtime_stack: AsyncExitStack | None = None
        self._active_session_id: str | None = None
        self._active_run: RunInfo | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._sequences: dict[str, int] = {}
        self._approval_waiters: dict[
            str,
            tuple[ApprovalRequest, asyncio.Future[tuple[ApprovalDecision, str | None]]],
        ] = {}
        self._session_grants: set[str] = set()

    @property
    def workspace(self) -> WorkspaceInfo | None:
        return self._workspace

    @property
    def active_run(self) -> RunInfo | None:
        return self._active_run

    async def open_workspace(self, path: str) -> dict[str, Any]:
        candidate = Path(path).expanduser()
        try:
            canonical = candidate.resolve(strict=True)
        except OSError as exc:
            raise DesktopRuntimeError("workspace_unavailable", f"Workspace is unavailable: {candidate}") from exc
        if not canonical.is_dir():
            raise DesktopRuntimeError("workspace_not_directory", f"Workspace is not a directory: {canonical}")
        if self._run_task is not None and not self._run_task.done():
            raise DesktopRuntimeError("run_active", "Cancel the active run before switching workspaces")

        await self._close_runtime()
        manager = ConfigManager(config_dir=self._config_dir, project_dir=canonical)
        config = manager.load()
        for key, value in config.env.items():
            if value:
                os.environ.setdefault(key, value)
        workspace_id = hashlib.sha256(str(canonical).encode()).hexdigest()[:16]
        guidance_sources = [
            str(item) for item in (canonical / "AGENTS.md", canonical / ".yaacli" / "config.toml") if item.is_file()
        ]
        self._workspace_path = canonical
        self._config_manager = manager
        self._config = config
        preferences = self._load_preferences(workspace_id)
        preferred_profile = preferences.get("active_profile")
        profiles = {profile.id: profile for profile in build_model_profiles(config)}
        preferred_theme = preferences.get("theme")
        if preferred_theme in THEME_NAMES:
            config.display.theme = preferred_theme
        startup = get_startup_model_profile(config, manager.config_dir)
        self._active_profile_name = (
            preferred_profile if isinstance(preferred_profile, str) and preferred_profile in profiles else None
        ) or (startup.id if startup else None)
        self._active_session_id = None
        self._session_grants.clear()
        self._workspace = WorkspaceInfo(
            id=workspace_id,
            path=str(canonical),
            name=canonical.name,
            guidance_sources=guidance_sources,
            config_sources=manager.loaded_sources,
            git_branch=_read_git_branch(canonical),
        )
        return self._workspace.model_dump(mode="json")

    async def create_session(self, name: str = "") -> SessionSnapshot:
        workspace, config, manager = self._require_workspace()
        session_id = new_session_id()
        store = self._store(session_id, workspace, config, manager)
        store.start()
        if name.strip():
            store.rename(name)
        self._active_session_id = session_id
        return self._snapshot(store)

    async def list_sessions(self) -> list[SessionSummary]:
        workspace, config, manager = self._require_workspace()
        probe = self._store("_listing", workspace, config, manager)
        return [
            self._listing_to_summary(item, workspace.id)
            for item in probe.listings()
            if self._same_workspace(item.working_dir)
        ]

    async def load_session(self, session_id: str) -> SessionSnapshot:
        workspace, config, manager = self._require_workspace()
        probe = self._store(session_id, workspace, config, manager)
        resolved = probe.resolve_session_id(session_id)
        if resolved is None:
            raise DesktopRuntimeError("session_not_found", f"Session not found: {session_id}")
        store = self._store(resolved, workspace, config, manager)
        store.start()
        listing = next((item for item in store.listings() if item.session_id == resolved), None)
        if listing is not None and not self._same_workspace(listing.working_dir):
            raise DesktopRuntimeError("session_workspace_mismatch", "Session belongs to a different workspace")
        self._active_session_id = resolved
        return self._snapshot(store)

    async def rename_session(self, session_id: str, name: str) -> SessionSummary:
        snapshot = await self.load_session(session_id)
        workspace, config, manager = self._require_workspace()
        store = self._store(snapshot.session.id, workspace, config, manager)
        store.start()
        store.rename(name)
        return self._snapshot(store).session

    async def archive_session(self, session_id: str) -> None:
        workspace, config, manager = self._require_workspace()
        if self._active_run is not None and self._active_run.session_id == session_id:
            raise DesktopRuntimeError("run_active", "Cannot archive a session with an active run")
        store = self._store(session_id, workspace, config, manager)
        resolved = store.resolve_session_id(session_id)
        if resolved is None:
            raise DesktopRuntimeError("session_not_found", f"Session not found: {session_id}")
        source = manager.get_sessions_dir() / resolved
        archive_dir = self._archive_dir(manager)
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(archive_dir / resolved))
        if self._active_session_id == resolved:
            self._active_session_id = None

    async def list_archived_sessions(self) -> list[SessionSummary]:
        workspace, _config, manager = self._require_workspace()
        archive_dir = self._archive_dir(manager)
        probe = TranscriptStore(
            sessions_dir=archive_dir,
            session_id="_archived_listing",
            working_dir=Path(workspace.path),
            model="",
        )
        summaries: list[SessionSummary] = []
        for item in probe.listings():
            if not self._same_workspace(item.working_dir):
                continue
            summary = self._listing_to_summary(item, workspace.id)
            summary.archived = True
            summaries.append(summary)
        return summaries

    async def restore_session(self, session_id: str) -> SessionSnapshot:
        workspace, config, manager = self._require_workspace()
        if self._active_run is not None and self._active_run.session_id == session_id:
            raise DesktopRuntimeError("run_active", "Cannot restore a session with an active run")
        archive_dir = self._archive_dir(manager)
        source = archive_dir / session_id
        if not source.is_dir():
            raise DesktopRuntimeError("session_not_found", f"Archived session not found: {session_id}")
        target_root = self._sessions_dir(config, manager)
        target_root.mkdir(parents=True, exist_ok=True)
        destination = target_root / session_id
        if destination.exists():
            raise DesktopRuntimeError("session_exists", f"A session already exists with id: {session_id}")
        shutil.move(str(source), str(destination))
        store = self._store(session_id, workspace, config, manager)
        store.start()
        self._active_session_id = session_id
        return self._snapshot(store)

    async def start_run(self, session_id: str, input_parts: list[InputPart]) -> str:
        if self._run_task is not None and not self._run_task.done():
            raise DesktopRuntimeError("run_active", "A run is already active")
        if not input_parts:
            raise DesktopRuntimeError("empty_input", "At least one input part is required")
        snapshot = await self.load_session(session_id)
        workspace, _config, _manager = self._require_workspace()
        run_id = uuid.uuid4().hex
        self._active_run = RunInfo(
            id=run_id,
            session_id=snapshot.session.id,
            workspace_id=workspace.id,
            status=RunStatus.RUNNING,
            steerable=True,
        )
        self._sequences[run_id] = 0
        self._run_task = asyncio.create_task(
            self._execute_run(self._active_run, input_parts),
            name=f"yaacli-desktop-run-{run_id}",
        )
        return run_id

    async def cancel_run(self, run_id: str) -> None:
        run = self._require_run(run_id)
        if self._run_task is None or self._run_task.done():
            raise DesktopRuntimeError("run_not_active", f"Run is not active: {run.id}")
        self._run_task.cancel()

    async def steer_run(self, run_id: str, text: str) -> None:
        run = self._require_run(run_id)
        if not text.strip():
            raise DesktopRuntimeError("empty_steering", "Steering text cannot be empty")
        runtime = self._runtime
        if runtime is None:
            raise DesktopRuntimeError("runtime_unavailable", "Runtime is not ready")
        runtime.ctx.send_message(text.strip(), source="user")
        await self._emit("steering.acknowledged", {"text": text.strip()}, run)

    async def resolve_approval(
        self,
        approval_id: str,
        workspace_id: str,
        session_id: str,
        run_id: str,
        decision: ApprovalDecision,
        reason: str | None = None,
    ) -> None:
        pending = self._approval_waiters.get(approval_id)
        if pending is None:
            raise DesktopRuntimeError("approval_not_pending", f"Approval is not pending: {approval_id}")
        request, waiter = pending
        if waiter.done():
            raise DesktopRuntimeError("approval_not_pending", f"Approval is not pending: {approval_id}")
        if request.workspace_id != workspace_id or request.session_id != session_id or request.run_id != run_id:
            raise DesktopRuntimeError(
                "approval_scope_mismatch", "Approval does not match the active workspace, session, and run"
            )
        waiter.set_result((decision, reason))

    async def config_snapshot(self) -> dict[str, Any]:
        _workspace, config, manager = self._require_workspace()
        profiles = {
            profile.id: {
                "label": profile.label or profile.id,
                "model": profile.model,
                "description": "",
            }
            for profile in build_model_profiles(config)
        }
        return {
            "configured": config.is_configured,
            "active_profile": self._active_profile_name,
            "profiles": profiles,
            "sources": manager.loaded_sources,
            "theme": config.display.theme,
        }

    async def update_config(self, *, active_profile: str | None = None, theme: str | None = None) -> dict[str, Any]:
        workspace, config, _manager = self._require_workspace()
        if self._active_run is not None:
            raise DesktopRuntimeError("run_active", "Configuration cannot change during an active run")
        if active_profile is not None:
            profile = get_model_profile(config, active_profile)
            if profile is None:
                raise DesktopRuntimeError("profile_not_found", f"Unknown model profile: {active_profile}")
            self._active_profile_name = active_profile
            save_selected_model_profile_id(self._config_manager.config_dir, active_profile)  # type: ignore[union-attr]
            await self._close_runtime()
        if theme is not None:
            if theme not in THEME_NAMES:
                raise DesktopRuntimeError("invalid_theme", f"Unsupported theme: {theme}")
            config.display.theme = theme  # type: ignore[assignment]
        self._save_preferences(
            workspace.id,
            {"active_profile": self._active_profile_name, "theme": config.display.theme},
        )
        return await self.config_snapshot()

    async def health(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "workspace_id": self._workspace.id if self._workspace else None,
            "active_run_id": self._active_run.id if self._active_run else None,
        }

    async def close(self) -> None:
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._run_task
        for _request, waiter in self._approval_waiters.values():
            if not waiter.done():
                waiter.cancel()
        self._approval_waiters.clear()
        await self._close_runtime()

    async def _ensure_runtime(self) -> Any:
        if self._runtime is not None:
            return self._runtime
        workspace, config, manager = self._require_workspace()
        if not config.is_configured:
            raise DesktopRuntimeError("not_configured", "YAACLI has no configured model profile")
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            model_profile = get_model_profile(config, self._active_profile_name) if self._active_profile_name else None
            runtime = create_tui_runtime(
                config=config,
                mcp_config=manager.load_mcp_config(),
                working_dir=Path(workspace.path),
                config_dir=manager.config_dir,
                model_profile=model_profile,
            )
            await stack.enter_async_context(runtime)
        except Exception:
            await stack.aclose()
            raise
        self._runtime_stack = stack
        self._runtime = runtime
        return runtime

    async def _close_runtime(self) -> None:
        stack = self._runtime_stack
        self._runtime = None
        self._runtime_stack = None
        if stack is not None:
            await stack.aclose()

    async def _execute_run(self, run: RunInfo, input_parts: list[InputPart]) -> None:
        workspace, config, manager = self._require_workspace()
        store = self._store(run.session_id, workspace, config, manager)
        store.start()
        user_content, display_text = self._build_user_content(input_parts)
        store.append_entry(kind="user", text=display_text, label="You")
        await self._emit("run.started", run.model_dump(mode="json"), run)
        assistant_chunks: list[str] = []
        pending_tools: dict[str, dict[str, Any]] = {}
        try:
            runtime = await self._ensure_runtime()
            message_history, _rebuilt = store.load_message_history_or_transcript()
            with suppress(Exception):
                store.restore_context_state(runtime)
            next_input: Any = user_content
            first = True
            while True:
                async with open_runtime_stream(
                    runtime,
                    config,
                    user_prompt=next_input if first else None,
                    message_history=message_history if first else None,
                    deferred_tool_results=next_input if not first else None,
                ) as stream:
                    async for raw_event in stream:
                        text_delta = await self._project_event(
                            raw_event, run, store=store, pending_tools=pending_tools
                        )
                        if text_delta:
                            self._append_assistant_chunk(assistant_chunks, raw_event, text_delta)
                    if hasattr(stream, "all_messages") and callable(stream.all_messages):
                        message_history = list(cast(Any, stream.all_messages()))
                        store.save_message_history(message_history, runtime)
                    result = getattr(getattr(stream, "run", None), "result", None)
                    output = getattr(result, "output", None)
                if not isinstance(output, DeferredToolRequests) or not output.approvals:
                    if isinstance(output, str) and not assistant_chunks:
                        assistant_chunks.append(output)
                        await self._emit("text.delta", {"delta": output}, run)
                    break
                next_input = await self._collect_approvals(output, run)
                first = False

            final_text = "".join(assistant_chunks).strip()
            if final_text:
                store.append_entry(kind="assistant", text=final_text, label="YAACLI")
            run.status = RunStatus.COMPLETED
            run.steerable = False
            await self._emit("run.completed", {"output_text": final_text}, run)
        except asyncio.CancelledError:
            run.status = RunStatus.CANCELLED
            run.steerable = False
            await self._emit("run.cancelled", {}, run)
            raise
        except Exception as exc:
            logger.exception("YAACLI Desktop run failed")
            run.status = RunStatus.FAILED
            run.steerable = False
            message = self._redact_text(str(exc) or type(exc).__name__)
            store.append_entry(kind="error", text=message, label=type(exc).__name__, error=True)
            await self._emit(
                "run.failed",
                {"error": {"code": type(exc).__name__, "message": message}},
                run,
            )
        finally:
            self._approval_waiters.clear()
            self._active_run = None

    @staticmethod
    def _append_assistant_chunk(chunks: list[str], raw_event: Any, text: str) -> None:
        event = getattr(raw_event, "event", raw_event)
        if chunks and isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
            chunks.append("\n\n")
        chunks.append(text)

    async def _collect_approvals(self, deferred: DeferredToolRequests, run: RunInfo) -> DeferredToolResults:
        results = DeferredToolResults()
        for tool_call in deferred.approvals:
            if tool_call.tool_name in self._session_grants:
                results.approvals[tool_call.tool_call_id] = True
                continue
            approval_id = f"approval-{run.id}-{tool_call.tool_call_id}"
            request = ApprovalRequest(
                id=approval_id,
                workspace_id=run.workspace_id,
                session_id=run.session_id,
                run_id=run.id,
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                summary=json.dumps(self._redact_value(tool_call.args), ensure_ascii=False, default=str)[:2000],
            )
            waiter: asyncio.Future[tuple[ApprovalDecision, str | None]] = asyncio.get_running_loop().create_future()
            self._approval_waiters[approval_id] = (request, waiter)
            run.status = RunStatus.WAITING_APPROVAL
            await self._emit("approval.requested", request.model_dump(mode="json"), run)
            decision, reason = await waiter
            self._approval_waiters.pop(approval_id, None)
            if decision == ApprovalDecision.APPROVE_SESSION:
                self._session_grants.add(tool_call.tool_name)
                results.approvals[tool_call.tool_call_id] = True
            elif decision == ApprovalDecision.APPROVE_ONCE:
                results.approvals[tool_call.tool_call_id] = True
            else:
                results.approvals[tool_call.tool_call_id] = ToolDenied(reason or "User rejected")
            run.status = RunStatus.RUNNING
            await self._emit(
                "approval.resolved",
                {"approval_id": approval_id, "decision": decision.value, "reason": reason},
                run,
            )
        return results

    async def _project_event(
        self,
        raw_event: Any,
        run: RunInfo,
        *,
        store: TranscriptStore | None = None,
        pending_tools: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        event = getattr(raw_event, "event", raw_event)
        if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
            content = event.part.content
            if content:
                await self._emit("text.delta", {"delta": content}, run)
            return content
        if isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart):
            if event.part.content:
                await self._emit("thinking.delta", {"delta": event.part.content}, run)
            return ""
        if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
            delta = event.delta.content_delta
            await self._emit("text.delta", {"delta": delta}, run)
            return delta
        if isinstance(event, PartDeltaEvent) and isinstance(event.delta, ThinkingPartDelta):
            await self._emit("thinking.delta", {"delta": event.delta.content_delta}, run)
            return ""
        if isinstance(event, FunctionToolCallEvent):
            tool_call_id = event.part.tool_call_id
            tool_name = event.part.tool_name
            args = self._redact_value(event.part.args)
            await self._emit(
                "tool.started",
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "args": args,
                },
                run,
            )
            if pending_tools is not None:
                pending_tools[tool_call_id] = {"name": tool_name, "args": args}
            return ""
        if isinstance(event, FunctionToolResultEvent):
            tool_call_id = getattr(event, "tool_call_id", "")
            result = self._redact_value(getattr(event, "result", None))
            await self._emit(
                "tool.completed",
                {
                    "tool_call_id": tool_call_id,
                    "result": result,
                },
                run,
            )
            if store is not None:
                # Persist one transcript entry per tool call (args + result) so
                # reopened sessions render the call as a collapsible card and
                # the transcript-derived message history keeps tool context.
                pending = (pending_tools or {}).pop(tool_call_id, {})
                tool_name = str(pending.get("name") or "tool")
                store.append_entry(
                    kind="tool",
                    text="",
                    label=tool_name,
                    tool={
                        "name": tool_name,
                        "args": pending.get("args"),
                        "result": result,
                        "tool_call_id": tool_call_id,
                    },
                )
            return ""
        if isinstance(event, ModelRequestStartEvent):
            await self._emit("run.phase", {"phase": "thinking", "loop_index": event.loop_index}, run)
            return ""
        if isinstance(event, ToolCallsStartEvent):
            await self._emit("run.phase", {"phase": "tools", "loop_index": event.loop_index}, run)
            return ""
        if isinstance(event, ContextUpdateEvent):
            usage = UsageInfo(total_tokens=event.total_tokens, context_window=event.context_window_size)
            await self._emit("usage.updated", usage.model_dump(mode="json"), run)
            return ""
        if isinstance(event, TaskEvent):
            tasks = [asdict(task) if is_dataclass(task) else dict(task) for task in event.tasks]
            await self._emit("task.updated", {"tasks": tasks}, run)
            return ""
        if isinstance(event, FileChangeEvent):
            for item in event.changes:
                action = str(getattr(item.action, "value", item.action))
                change_type = "renamed" if action in {"moved", "renamed"} else action
                if change_type not in {"added", "modified", "deleted", "renamed"}:
                    change_type = "modified"
                diff_chunks: list[str] = []
                for replacement in getattr(item, "replacements", []):
                    old = str(getattr(replacement, "old_string", ""))
                    new = str(getattr(replacement, "new_string", ""))
                    diff_chunks.extend(
                        difflib.unified_diff(
                            old.splitlines(),
                            new.splitlines(),
                            fromfile=f"a/{item.path}",
                            tofile=f"b/{item.destination or item.path}",
                            lineterm="",
                        )
                    )
                rendered_diff = "\n".join(diff_chunks)[:65536] or None
                change = FileChange(
                    path=item.destination or item.path if change_type == "renamed" else item.path,
                    old_path=item.path if change_type == "renamed" else None,
                    change_type=change_type,  # type: ignore[arg-type]
                    diff=rendered_diff,
                    diff_available=rendered_diff is not None,
                )
                await self._emit("file.changed", change.model_dump(mode="json"), run)
        return ""

    async def _emit(self, event: str, payload: dict[str, Any], run: RunInfo) -> None:
        sequence = self._sequences.get(run.id, 0)
        self._sequences[run.id] = sequence + 1
        await self._event_sink(
            EventEnvelope(
                event=event,
                payload=self._redact_value(payload),
                workspace_id=run.workspace_id,
                session_id=run.session_id,
                run_id=run.id,
                sequence=sequence,
            )
        )

    def _build_user_content(self, parts: list[InputPart]) -> tuple[Any, str]:
        if len(parts) > 32:
            raise DesktopRuntimeError("too_many_attachments", "Input contains too many parts")
        content: list[Any] = []
        display: list[str] = []
        for part in parts:
            if part.type == InputPartType.TEXT:
                text = part.text or ""
                if text:
                    content.append(text)
                    display.append(text)
                continue
            path = Path(part.path).expanduser() if part.path else None
            if part.data_base64:
                try:
                    data = base64.b64decode(part.data_base64, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise DesktopRuntimeError("invalid_attachment", "Inline attachment is not valid base64") from exc
                attachment_name = part.name or "clipboard-image"
            elif path is not None:
                try:
                    size = path.stat().st_size
                except OSError as exc:
                    raise DesktopRuntimeError("attachment_unavailable", f"Attachment is unavailable: {path}") from exc
                if size > _MAX_ATTACHMENT_BYTES:
                    raise DesktopRuntimeError("attachment_too_large", f"Attachment exceeds 20 MiB: {path.name}")
                data = path.read_bytes()
                attachment_name = part.name or path.name
            else:
                raise DesktopRuntimeError("invalid_attachment", "Attachment path or inline data is required")
            if len(data) > _MAX_ATTACHMENT_BYTES:
                raise DesktopRuntimeError("attachment_too_large", f"Attachment exceeds 20 MiB: {attachment_name}")
            media_type = part.media_type or (
                "image/png" if part.type == InputPartType.IMAGE else "application/octet-stream"
            )
            content.append(BinaryContent(data=data, media_type=media_type))
            display.append(f"[Attachment: {attachment_name}]")
        if not content:
            raise DesktopRuntimeError("empty_input", "Input does not contain usable content")
        return (content[0] if len(content) == 1 else content), "\n\n".join(display)

    def _store(
        self,
        session_id: str,
        workspace: WorkspaceInfo,
        config: YaacliConfig,
        manager: ConfigManager,
    ) -> TranscriptStore:
        startup = (
            get_model_profile(config, self._active_profile_name)
            if self._active_profile_name
            else get_startup_model_profile(config, manager.config_dir)
        )
        model = startup.model if startup else ""
        sessions_dir = self._sessions_dir(config, manager)
        return TranscriptStore(
            sessions_dir=sessions_dir,
            session_id=session_id,
            working_dir=Path(workspace.path),
            model=model,
            max_sessions=config.session.max_sessions,
        )

    def _sessions_dir(self, config: YaacliConfig, manager: ConfigManager) -> Path:
        raw_session_dir = config.session.session_dir.strip()
        if raw_session_dir:
            return Path(raw_session_dir).expanduser()
        return manager.get_sessions_dir()

    def _archive_dir(self, manager: ConfigManager) -> Path:
        return manager.config_dir / "archived-sessions"

    def _snapshot(self, store: TranscriptStore) -> SessionSnapshot:
        workspace, _config, _manager = self._require_workspace()
        listing = next((item for item in store.listings() if item.session_id == store.session_id), None)
        if listing is None:
            raise DesktopRuntimeError("session_not_found", f"Session not found: {store.session_id}")
        status = (
            self._active_run.status
            if self._active_run and self._active_run.session_id == store.session_id
            else RunStatus.IDLE
        )
        return SessionSnapshot(
            session=self._listing_to_summary(listing, workspace.id),
            transcript=store.transcript(),
            run_status=status,
        )

    def _listing_to_summary(self, listing: Any, workspace_id: str) -> SessionSummary:
        return SessionSummary(
            id=listing.session_id,
            name=listing.name or "New session",
            latest_user_prompt=listing.latest_user_prompt,
            updated_at=listing.updated_at,
            workspace_id=workspace_id,
            model=listing.model,
        )

    def _same_workspace(self, path: str) -> bool:
        if self._workspace_path is None:
            return False
        try:
            return Path(path).resolve() == self._workspace_path
        except OSError:
            return False

    def _require_workspace(self) -> tuple[WorkspaceInfo, YaacliConfig, ConfigManager]:
        if self._workspace is None or self._config is None or self._config_manager is None:
            raise DesktopRuntimeError("workspace_required", "Open a workspace first")
        return self._workspace, self._config, self._config_manager

    def _require_run(self, run_id: str) -> RunInfo:
        run = self._active_run
        if run is None or run.id != run_id:
            raise DesktopRuntimeError("run_not_found", f"Active run not found: {run_id}")
        return run

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): self._redact_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact_value(item) for item in value]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self._redact_text(str(value))

    def _redact_text(self, text: str) -> str:
        redacted = _TOKEN_PATTERN.sub(lambda match: f"{match.group(1) if match.lastindex else ''}[REDACTED]", text)
        if self._config is not None:
            for secret in self._config.env.values():
                if secret and len(secret) >= 6:
                    redacted = redacted.replace(secret, "[REDACTED]")
        return redacted

    def _preferences_path(self) -> Path:
        config_dir = self._config_manager.config_dir if self._config_manager else self._config_dir
        return (config_dir or ConfigManager.DEFAULT_CONFIG_DIR) / "desktop-state.json"

    def _load_preferences(self, workspace_id: str) -> dict[str, Any]:
        path = self._preferences_path()
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError, ValueError):
            return {}
        value = data.get("workspaces", {}).get(workspace_id, {}) if isinstance(data, dict) else {}
        return value if isinstance(value, dict) else {}

    def _save_preferences(self, workspace_id: str, preferences: dict[str, Any]) -> None:
        path = self._preferences_path()
        try:
            data = json.loads(path.read_text()) if path.exists() else {}
        except (OSError, json.JSONDecodeError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        workspaces = data.setdefault("workspaces", {})
        if not isinstance(workspaces, dict):
            workspaces = {}
            data["workspaces"] = workspaces
        workspaces[workspace_id] = self._redact_value(preferences)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        temporary.replace(path)
