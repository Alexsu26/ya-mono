"""Versioned wire protocol shared by YAACLI Desktop and its sidecar."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_PENDING_REQUESTS = 64
MAX_ATTACHMENTS = 32

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class ProtocolModel(BaseModel):
    """Strict base class for protocol values."""

    model_config = ConfigDict(extra="forbid")


class InputPartType(StrEnum):
    TEXT = "text"
    FILE = "file"
    IMAGE = "image"


class RunStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class InputPart(ProtocolModel):
    type: InputPartType
    text: str | None = None
    path: str | None = None
    media_type: str | None = None
    name: str | None = None
    data_base64: str | None = None


class WorkspaceInfo(ProtocolModel):
    id: Identifier
    path: str
    name: str
    available: bool = True
    guidance_sources: list[str] = Field(default_factory=list)
    config_sources: list[str] = Field(default_factory=list)
    git_branch: str | None = None


class SessionSummary(ProtocolModel):
    id: Identifier
    name: str
    latest_user_prompt: str = ""
    updated_at: str = ""
    workspace_id: Identifier
    model: str = ""
    archived: bool = False


class SessionSnapshot(ProtocolModel):
    session: SessionSummary
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    run_status: RunStatus = RunStatus.IDLE


class RunInfo(ProtocolModel):
    id: Identifier
    session_id: Identifier
    workspace_id: Identifier
    status: RunStatus
    steerable: bool = False


class ApprovalDecision(StrEnum):
    APPROVE_ONCE = "approve_once"
    APPROVE_SESSION = "approve_session"
    DENY = "deny"


class ApprovalRequest(ProtocolModel):
    id: Identifier
    workspace_id: Identifier
    session_id: Identifier
    run_id: Identifier
    tool_call_id: Identifier
    tool_name: str
    summary: str
    risk: str = "runtime_review"
    decisions: list[ApprovalDecision] = Field(
        default_factory=lambda: [
            ApprovalDecision.APPROVE_ONCE,
            ApprovalDecision.APPROVE_SESSION,
            ApprovalDecision.DENY,
        ]
    )


class FileChange(ProtocolModel):
    path: str
    change_type: Literal["added", "modified", "deleted", "renamed"]
    old_path: str | None = None
    diff: str | None = None
    diff_available: bool = False
    binary: bool = False


class UsageInfo(ProtocolModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    context_window: int | None = None
    cost: float | None = None


class RuntimeHealth(ProtocolModel):
    status: Literal["starting", "ready", "unavailable", "stopping"]
    workspace_id: str | None = None
    active_run_id: str | None = None
    message: str | None = None


class ProtocolCapabilities(ProtocolModel):
    commands: list[str]
    events: list[str]
    max_message_bytes: int = MAX_MESSAGE_BYTES
    max_attachments: int = MAX_ATTACHMENTS
    steering: bool = True
    approvals: bool = True


class HandshakeEnvelope(ProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["handshake"] = "handshake"
    runtime_version: str
    capabilities: ProtocolCapabilities


class RequestEnvelope(ProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["request"] = "request"
    request_id: Identifier
    command: Identifier
    payload: dict[str, Any] = Field(default_factory=dict)


class ErrorInfo(ProtocolModel):
    code: str
    message: str
    retryable: bool = False


class ResponseEnvelope(ProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["response"] = "response"
    request_id: Identifier
    ok: bool
    payload: dict[str, Any] | None = None
    error: ErrorInfo | None = None


class EventEnvelope(ProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["event"] = "event"
    event: Identifier
    payload: dict[str, Any] = Field(default_factory=dict)
    workspace_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    sequence: int | None = Field(default=None, ge=0)


WireEnvelope = HandshakeEnvelope | RequestEnvelope | ResponseEnvelope | EventEnvelope


SUPPORTED_COMMANDS = [
    "runtime.health",
    "workspace.open",
    "session.create",
    "session.list",
    "session.list_archived",
    "session.load",
    "session.rename",
    "session.archive",
    "session.restore",
    "run.start",
    "run.cancel",
    "run.steer",
    "approval.resolve",
    "config.get",
    "config.update",
    "runtime.shutdown",
]

SUPPORTED_EVENTS = [
    "runtime.health",
    "run.started",
    "run.phase",
    "text.delta",
    "thinking.delta",
    "tool.started",
    "tool.completed",
    "task.updated",
    "usage.updated",
    "file.changed",
    "approval.requested",
    "approval.resolved",
    "steering.acknowledged",
    "run.completed",
    "run.cancelled",
    "run.failed",
]
