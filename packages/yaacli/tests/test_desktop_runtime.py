"""Tests for the UI-independent YAACLI Desktop runtime service."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolReturnPart,
)
from ya_agent_sdk.events import FileChange as SdkFileChange
from ya_agent_sdk.events import FileChangeAction, FileChangeEvent, TextReplacement
from yaacli.console.transcript import TranscriptStore
from yaacli.desktop.protocol import (
    ApprovalDecision,
    EventEnvelope,
    InputPart,
    InputPartType,
    RunInfo,
    RunStatus,
)
from yaacli.desktop.runtime import DesktopRuntimeError, DesktopRuntimeService


async def sink(_event: EventEnvelope) -> None:
    return None


@pytest.mark.asyncio
async def test_workspace_sessions_are_created_listed_restored_and_renamed(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    service = DesktopRuntimeService(sink, config_dir=config_dir)

    opened = await service.open_workspace(str(workspace))
    created = await service.create_session("Initial name")
    renamed = await service.rename_session(created.session.id, "Renamed")
    listed = await service.list_sessions()
    restored = await service.load_session(created.session.id)

    assert opened["path"] == str(workspace.resolve())
    assert renamed.name == "Renamed"
    assert [item.id for item in listed] == [created.session.id]
    assert restored.session.name == "Renamed"
    await service.close()


@pytest.mark.asyncio
async def test_workspace_switch_isolates_session_listing(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    service = DesktopRuntimeService(sink, config_dir=tmp_path / "config")

    await service.open_workspace(str(first))
    created = await service.create_session()
    await service.open_workspace(str(second))

    assert await service.list_sessions() == []
    with pytest.raises(DesktopRuntimeError, match="different workspace"):
        await service.load_session(created.session.id)
    await service.close()


@pytest.mark.asyncio
async def test_archiving_preserves_session_outside_active_listing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_dir = tmp_path / "config"
    service = DesktopRuntimeService(sink, config_dir=config_dir)

    await service.open_workspace(str(workspace))
    created = await service.create_session()
    await service.archive_session(created.session.id)

    assert await service.list_sessions() == []
    assert (config_dir / "archived-sessions" / created.session.id).is_dir()
    await service.close()


def test_session_auto_name_tracks_latest_prompt_until_explicit_rename(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(
        sessions_dir=tmp_path / "sessions",
        session_id="s1",
        working_dir=tmp_path,
        model="test:model",
    )
    store.start()
    store.append_entry(kind="user", text="first question", label="You")
    assert store._metadata["name"] == "first question"

    # Auto-naming follows the most recent prompt, not the first.
    store.append_entry(kind="user", text="second question", label="You")
    assert store._metadata["name"] == "second question"
    assert store._metadata["latest_user_prompt"] == "second question"

    # An explicit rename wins and is preserved across later prompts.
    store.rename("My Session")
    store.append_entry(kind="user", text="third question", label="You")
    assert store._metadata["name"] == "My Session"
    assert store._metadata["name_source"] == "explicit"
    assert store._metadata["latest_user_prompt"] == "third question"


@pytest.mark.asyncio
async def test_archived_sessions_are_listed_and_restorable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_dir = tmp_path / "config"
    service = DesktopRuntimeService(sink, config_dir=config_dir)

    await service.open_workspace(str(workspace))
    created = await service.create_session("Important")

    archived = await service.list_archived_sessions()
    assert archived == []

    await service.archive_session(created.session.id)
    archived = await service.list_archived_sessions()
    assert [item.id for item in archived] == [created.session.id]
    assert archived[0].archived is True
    assert archived[0].name == "Important"

    restored = await service.restore_session(created.session.id)
    assert restored.session.name == "Important"
    assert restored.session.id == created.session.id
    assert await service.list_sessions() == [restored.session]
    assert await service.list_archived_sessions() == []
    await service.close()


@pytest.mark.asyncio
async def test_unavailable_workspace_fails_without_starting_runtime(tmp_path: Path) -> None:
    service = DesktopRuntimeService(sink, config_dir=tmp_path / "config")

    with pytest.raises(DesktopRuntimeError, match="unavailable"):
        await service.open_workspace(str(tmp_path / "missing"))

    assert service.workspace is None


@pytest.mark.asyncio
async def test_open_workspace_reports_git_branch_from_head(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    (workspace / ".git" / "HEAD").write_text("ref: refs/heads/feat/cool\n")
    service = DesktopRuntimeService(sink, config_dir=tmp_path / "config")

    opened = await service.open_workspace(str(workspace))

    assert opened["git_branch"] == "feat/cool"
    await service.close()


@pytest.mark.asyncio
async def test_open_workspace_branch_none_when_detached_or_not_a_repo(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    # Detached HEAD: a raw object id, not a ref pointer.
    (workspace / ".git" / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n")
    service = DesktopRuntimeService(sink, config_dir=tmp_path / "config")

    detached = await service.open_workspace(str(workspace))
    await service.close()

    bare = tmp_path / "bare"
    bare.mkdir()
    service2 = DesktopRuntimeService(sink, config_dir=tmp_path / "config2")
    not_repo = await service2.open_workspace(str(bare))

    assert detached["git_branch"] is None
    assert not_repo["git_branch"] is None
    await service2.close()


@pytest.mark.asyncio
async def test_workspace_config_environment_is_available_to_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    config_dir = tmp_path / "config"
    workspace.mkdir()
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[general]\nmodel = "test:model"\n\n[env]\nDESKTOP_TEST_API_KEY = "configured"\n'
    )
    monkeypatch.delenv("DESKTOP_TEST_API_KEY", raising=False)
    service = DesktopRuntimeService(sink, config_dir=config_dir)

    await service.open_workspace(str(workspace))

    assert os.environ["DESKTOP_TEST_API_KEY"] == "configured"
    await service.close()


@pytest.mark.asyncio
async def test_stream_projection_preserves_initial_text_and_thinking_chunks(
    tmp_path: Path,
) -> None:
    events: list[EventEnvelope] = []

    async def capture(event: EventEnvelope) -> None:
        events.append(event)

    service = DesktopRuntimeService(capture, config_dir=tmp_path / "config")
    run = RunInfo(
        id="run-1",
        workspace_id="workspace-1",
        session_id="session-1",
        status=RunStatus.RUNNING,
    )

    first = await service._project_event(
        PartStartEvent(index=0, part=TextPart(content="Hi")),
        run,
    )
    second = await service._project_event(
        PartDeltaEvent(index=0, delta=TextPartDelta(content_delta="!")),
        run,
    )
    await service._project_event(
        PartStartEvent(index=1, part=ThinkingPart(content="Check")),
        run,
    )
    await service._project_event(
        PartDeltaEvent(index=1, delta=ThinkingPartDelta(content_delta=" context")),
        run,
    )

    assert first + second == "Hi!"
    assert [(event.event, event.payload["delta"]) for event in events] == [
        ("text.delta", "Hi"),
        ("text.delta", "!"),
        ("thinking.delta", "Check"),
        ("thinking.delta", " context"),
    ]

    chunks = ["First response."]
    service._append_assistant_chunk(
        chunks,
        PartStartEvent(index=2, part=TextPart(content="Second response")),
        "Second response",
    )
    service._append_assistant_chunk(
        chunks,
        PartDeltaEvent(index=2, delta=TextPartDelta(content_delta="!")),
        "!",
    )
    assert "".join(chunks) == "First response.\n\nSecond response!"


@pytest.mark.asyncio
async def test_tool_calls_are_persisted_to_transcript_for_replay(tmp_path: Path) -> None:
    events: list[EventEnvelope] = []

    async def capture(event: EventEnvelope) -> None:
        events.append(event)

    service = DesktopRuntimeService(capture, config_dir=tmp_path / "config")
    run = RunInfo(
        id="run-1",
        workspace_id="workspace-1",
        session_id="session-1",
        status=RunStatus.RUNNING,
    )
    store = TranscriptStore(
        sessions_dir=tmp_path / "sessions",
        session_id="session-1",
        working_dir=tmp_path,
        model="test:model",
    )
    store.start()
    pending: dict[str, dict[str, Any]] = {}

    await service._project_event(
        FunctionToolCallEvent(
            part=ToolCallPart(
                tool_name="list_files",
                args={"path": "apps/yaacli-desktop"},
                tool_call_id="tc-1",
            )
        ),
        run,
        store=store,
        pending_tools=pending,
    )
    # Nothing is written until the result arrives; args are buffered by call id.
    assert store.transcript() == []
    assert pending == {
        "tc-1": {"name": "list_files", "args": {"path": "apps/yaacli-desktop"}}
    }

    await service._project_event(
        FunctionToolResultEvent(
            part=ToolReturnPart(
                tool_name="list_files",
                content='[{"name":"README.md"}]',
                tool_call_id="tc-1",
            )
        ),
        run,
        store=store,
        pending_tools=pending,
    )

    entries = store.transcript()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["kind"] == "tool"
    assert entry["label"] == "list_files"
    tool = entry["tool"]
    assert tool["name"] == "list_files"
    assert tool["args"] == {"path": "apps/yaacli-desktop"}
    assert tool["tool_call_id"] == "tc-1"
    assert "README.md" in json.dumps(tool["result"], default=str)
    # Buffered args are consumed once the result is persisted.
    assert pending == {}
    # Phase events still fire for the live stream.
    assert [event.event for event in events] == ["tool.started", "tool.completed"]


def test_redaction_removes_bearer_and_provider_tokens(tmp_path: Path) -> None:
    service = DesktopRuntimeService(sink, config_dir=tmp_path / "config")

    redacted = service._redact_value({"authorization": "Bearer secret-token", "key": "sk-abcdefghijklmnop"})

    assert redacted == {"authorization": "Bearer [REDACTED]", "key": "[REDACTED]"}


def test_inline_clipboard_image_is_decoded_as_binary_content(tmp_path: Path) -> None:
    service = DesktopRuntimeService(sink, config_dir=tmp_path / "config")
    encoded = base64.b64encode(b"image-bytes").decode()

    content, display = service._build_user_content([
        InputPart(
            type=InputPartType.IMAGE,
            name="clipboard.png",
            media_type="image/png",
            data_base64=encoded,
        )
    ])

    assert content.data == b"image-bytes"
    assert content.media_type == "image/png"
    assert display == "[Attachment: clipboard.png]"


def test_invalid_inline_attachment_is_rejected(tmp_path: Path) -> None:
    service = DesktopRuntimeService(sink, config_dir=tmp_path / "config")

    with pytest.raises(DesktopRuntimeError, match="valid base64"):
        service._build_user_content([InputPart(type=InputPartType.IMAGE, data_base64="not-base64!")])


@pytest.mark.asyncio
async def test_approval_requires_matching_scope_and_allows_once(tmp_path: Path) -> None:
    events: list[EventEnvelope] = []

    async def capture(event: EventEnvelope) -> None:
        events.append(event)

    service = DesktopRuntimeService(capture, config_dir=tmp_path / "config")
    run = RunInfo(
        id="run-1",
        workspace_id="workspace-1",
        session_id="session-1",
        status=RunStatus.RUNNING,
    )
    deferred = DeferredToolRequests(
        approvals=[ToolCallPart(tool_name="shell", args={"command": "pwd"}, tool_call_id="tool-1")]
    )
    collecting = asyncio.create_task(service._collect_approvals(deferred, run))
    while not service._approval_waiters:
        await asyncio.sleep(0)
    approval = next(iter(service._approval_waiters.values()))[0]

    with pytest.raises(DesktopRuntimeError, match="does not match"):
        await service.resolve_approval(
            approval.id,
            "wrong-workspace",
            approval.session_id,
            approval.run_id,
            ApprovalDecision.APPROVE_ONCE,
        )

    await service.resolve_approval(
        approval.id,
        approval.workspace_id,
        approval.session_id,
        approval.run_id,
        ApprovalDecision.APPROVE_ONCE,
    )
    results = await collecting

    assert results.approvals["tool-1"] is True
    assert [event.event for event in events] == ["approval.requested", "approval.resolved"]


@pytest.mark.asyncio
async def test_pending_approval_fails_closed_when_service_closes(tmp_path: Path) -> None:
    service = DesktopRuntimeService(sink, config_dir=tmp_path / "config")
    run = RunInfo(
        id="run-1",
        workspace_id="workspace-1",
        session_id="session-1",
        status=RunStatus.RUNNING,
    )
    deferred = DeferredToolRequests(approvals=[ToolCallPart(tool_name="shell", args={}, tool_call_id="tool-1")])
    collecting = asyncio.create_task(service._collect_approvals(deferred, run))
    while not service._approval_waiters:
        await asyncio.sleep(0)

    await service.close()

    with pytest.raises(asyncio.CancelledError):
        await collecting


@pytest.mark.asyncio
async def test_denied_approval_returns_tool_denial(tmp_path: Path) -> None:
    service = DesktopRuntimeService(sink, config_dir=tmp_path / "config")
    run = RunInfo(
        id="run-1",
        workspace_id="workspace-1",
        session_id="session-1",
        status=RunStatus.RUNNING,
    )
    deferred = DeferredToolRequests(approvals=[ToolCallPart(tool_name="shell", args={}, tool_call_id="tool-1")])
    collecting = asyncio.create_task(service._collect_approvals(deferred, run))
    while not service._approval_waiters:
        await asyncio.sleep(0)
    approval = next(iter(service._approval_waiters.values()))[0]

    await service.resolve_approval(
        approval.id,
        approval.workspace_id,
        approval.session_id,
        approval.run_id,
        ApprovalDecision.DENY,
        "not allowed",
    )
    results = await collecting

    assert "not allowed" in str(results.approvals["tool-1"])


@pytest.mark.asyncio
async def test_configured_secret_is_redacted_from_nested_protocol_values(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_dir = tmp_path / "config"
    workspace.mkdir()
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('[env]\nAPI_TOKEN = "supersecret"\n')
    service = DesktopRuntimeService(sink, config_dir=config_dir)
    await service.open_workspace(str(workspace))

    redacted = service._redact_value({"args": ["supersecret", {"value": "prefix-supersecret"}]})

    assert redacted == {"args": ["[REDACTED]", {"value": "prefix-[REDACTED]"}]}


@pytest.mark.asyncio
async def test_desktop_profile_and_theme_preferences_persist_per_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_dir = tmp_path / "config"
    workspace.mkdir()
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[models.fast]\nmodel = "openai-chat:gpt-4"\n\n[models.deep]\nmodel = "deepseek:deepseek-chat"\n'
    )
    first = DesktopRuntimeService(sink, config_dir=config_dir)
    await first.open_workspace(str(workspace))

    updated = await first.update_config(active_profile="deep", theme="light")
    await first.close()
    second = DesktopRuntimeService(sink, config_dir=config_dir)
    await second.open_workspace(str(workspace))
    restored = await second.config_snapshot()

    assert updated["active_profile"] == "deep"
    assert restored["active_profile"] == "deep"
    assert restored["theme"] == "light"
    assert "deepseek:deepseek-chat" not in (config_dir / "desktop-state.json").read_text()


@pytest.mark.asyncio
async def test_file_replacements_produce_reviewable_diff(tmp_path: Path) -> None:
    events: list[EventEnvelope] = []

    async def capture(event: EventEnvelope) -> None:
        events.append(event)

    service = DesktopRuntimeService(capture, config_dir=tmp_path / "config")
    run = RunInfo(
        id="run-1",
        workspace_id="workspace-1",
        session_id="session-1",
        status=RunStatus.RUNNING,
    )
    event = FileChangeEvent(
        event_id="file-change-1",
        changes=[
            SdkFileChange(
                path="README.md",
                action=FileChangeAction.modified,
                replacements=[TextReplacement(old_string="old", new_string="new")],
            )
        ],
        tool_name="edit",
    )

    await service._project_event(event, run)

    change = events[0].payload
    assert change["diff_available"] is True
    assert "-old" in change["diff"]
    assert "+new" in change["diff"]
