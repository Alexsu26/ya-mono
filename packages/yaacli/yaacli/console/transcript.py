"""Local transcript persistence for the Textual console."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from ya_agent_sdk.context import ResumableState

_LEGACY_TOOL_MARKER_RE = re.compile(r"\[tool:[^\]\r\n]+\]")
_INJECTED_USER_CONTEXT_PREFIXES = (
    "<agent_behavior",
    "<environment-context",
    "<project-guidance",
    "<runtime-context",
)


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return default


def _session_name(value: Any) -> str:
    for line in str(value or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def strip_legacy_tool_protocol(text: str) -> str:
    """Remove leaked internal tool protocol and everything after it."""
    marker = _LEGACY_TOOL_MARKER_RE.search(text)
    return text[: marker.start()].rstrip() if marker is not None else text


def _transcript_user_prompts(path: Path) -> tuple[str, str]:
    first = ""
    latest = ""
    entries = _read_json(path, [])
    if not isinstance(entries, list):
        return first, latest
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("kind") != "user":
            continue
        prompt = _session_name(entry.get("text"))
        if not prompt or prompt.lstrip().startswith("/"):
            continue
        if not first:
            first = prompt
        latest = prompt
    return first, latest


def _visible_user_prompt(content: Any) -> str:
    values = [content] if isinstance(content, str) else content if isinstance(content, (list, tuple)) else []
    for value in values:
        if not isinstance(value, str):
            continue
        prompt = value.strip()
        if prompt and not prompt.startswith(_INJECTED_USER_CONTEXT_PREFIXES):
            return prompt
    return ""


def _transcript_from_message_history(messages: list[Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if not isinstance(part, UserPromptPart):
                    continue
                prompt = _visible_user_prompt(part.content)
                if prompt:
                    entries.append({"kind": "user", "label": "user", "text": prompt})
        elif isinstance(message, ModelResponse):
            chunks = [strip_legacy_tool_protocol(part.content) for part in message.parts if isinstance(part, TextPart)]
            text = "\n\n".join(chunk for chunk in chunks if chunk)
            if text:
                entries.append({"kind": "assistant", "label": "assistant", "text": text})
    return entries


def _message_history_transcript(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with suppress(Exception):
        messages = list(ModelMessagesTypeAdapter.validate_json(path.read_bytes()))
        return _transcript_from_message_history(messages)
    return []


def _message_history_from_transcript(entries: list[dict[str, Any]]) -> list[Any]:
    messages: list[Any] = []
    assistant_chunks: list[str] = []

    def flush_assistant() -> None:
        if not assistant_chunks:
            return
        messages.append(ModelResponse(parts=[TextPart(content="\n\n".join(assistant_chunks))]))
        assistant_chunks.clear()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "")
        text = str(entry.get("text") or "")
        label = str(entry.get("label") or kind or "entry")
        if kind == "user":
            if not text or text.lstrip().startswith("/"):
                continue
            flush_assistant()
            messages.append(ModelRequest(parts=[UserPromptPart(content=text)]))
        elif kind == "assistant":
            clean_text = strip_legacy_tool_protocol(text)
            if clean_text:
                assistant_chunks.append(clean_text)
        elif kind == "tool":
            tool = entry.get("tool")
            if not isinstance(tool, dict):
                # Legacy transcript entries lack enough information to form a
                # valid tool call/result pair. Omitting them is safer than
                # teaching the model a fake `[tool:name]` text protocol.
                continue
            name = str(tool.get("name") or label or "tool")
            tool_call_id = str(tool.get("tool_call_id") or f"transcript-tool-{index}")
            flush_assistant()
            messages.append(
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name=name,
                            args=tool.get("args"),
                            tool_call_id=tool_call_id,
                        )
                    ]
                )
            )
            messages.append(
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name=name,
                            content=tool.get("result"),
                            tool_call_id=tool_call_id,
                            outcome="failed" if entry.get("error") else "success",
                        )
                    ]
                )
            )

    flush_assistant()
    return messages


def _has_legacy_tool_markers(messages: list[Any]) -> bool:
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            if isinstance(part, TextPart) and _LEGACY_TOOL_MARKER_RE.search(part.content):
                return True
    return False


@dataclass(frozen=True)
class SessionListing:
    session_id: str
    name: str
    latest_user_prompt: str
    updated_at: str
    working_dir: str
    model: str
    path: Path


class TranscriptStore:
    """Durable session files under ``~/.yaacli/sessions/<id>/``."""

    def __init__(
        self,
        *,
        sessions_dir: Path,
        session_id: str,
        working_dir: Path,
        model: str,
        max_sessions: int = 100,
    ) -> None:
        self.sessions_dir = sessions_dir
        self.session_id = session_id
        self.working_dir = working_dir
        self.model = model
        self.max_sessions = max_sessions
        self.session_dir = self.sessions_dir / self.session_id
        self._transcript: list[dict[str, Any]] = []
        self._metadata: dict[str, Any] = {}

    @property
    def metadata_path(self) -> Path:
        return self.session_dir / "metadata.json"

    @property
    def transcript_path(self) -> Path:
        return self.session_dir / "transcript.json"

    @property
    def message_history_path(self) -> Path:
        return self.session_dir / "message_history.json"

    @property
    def context_state_path(self) -> Path:
        return self.session_dir / "context_state.json"

    def start(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        now = utc_now()
        self._metadata = _read_json(self.metadata_path, {})
        if not self._metadata:
            self._metadata = {
                "session_id": self.session_id,
                "name": "",
                "name_source": "",
                "latest_user_prompt": "",
                "working_dir": str(self.working_dir),
                "created_at": now,
                "updated_at": now,
                "model": self.model,
                "turns": [],
                "tool_count": 0,
                "error_count": 0,
            }
        else:
            self._metadata["session_id"] = self.session_id
            self._metadata["updated_at"] = now
            self._metadata["model"] = self.model
        self._transcript = list(_read_json(self.transcript_path, []))
        self._save_metadata()
        self._prune_old_sessions()

    def switch(self, session_id: str) -> None:
        self.session_id = session_id
        self.session_dir = self.sessions_dir / self.session_id
        self.start()

    def has_data(self) -> bool:
        return bool(self._transcript) or self.message_history_path.exists()

    def append_entry(
        self,
        *,
        kind: str,
        text: str,
        label: str = "",
        error: bool = False,
        tool: dict[str, Any] | None = None,
    ) -> None:
        if not text and kind != "tool":
            return
        entry = {
            "kind": kind,
            "label": label,
            "text": text,
            "error": error,
            "created_at": utc_now(),
        }
        if kind == "tool" and tool is not None:
            entry["tool"] = json.loads(json.dumps(tool, ensure_ascii=False, default=str))
        self._transcript.append(entry)
        if kind == "tool":
            self._metadata["tool_count"] = int(self._metadata.get("tool_count", 0)) + 1
        if error or kind == "error":
            self._metadata["error_count"] = int(self._metadata.get("error_count", 0)) + 1
        if kind == "user":
            prompt = _session_name(text)
            if prompt and not prompt.lstrip().startswith("/"):
                self._metadata["latest_user_prompt"] = prompt
                # Auto-name tracks the most recent prompt so the session list
                # reflects the current topic. An explicit rename wins and is
                # preserved across subsequent prompts.
                if self._metadata.get("name_source") != "explicit":
                    self._metadata["name"] = prompt
                    self._metadata["name_source"] = "auto"
        self._metadata["updated_at"] = utc_now()
        _write_json(self.transcript_path, self._transcript)
        self._save_metadata()

    def clear_state_snapshot(self) -> None:
        for path in (self.message_history_path, self.context_state_path):
            with suppress(FileNotFoundError):
                path.unlink()

    def clear_transcript(self) -> None:
        self._transcript = []
        self._metadata["latest_user_prompt"] = ""
        if self._metadata.get("name_source") == "auto":
            self._metadata["name"] = ""
            self._metadata["name_source"] = ""
        self._metadata["updated_at"] = utc_now()
        _write_json(self.transcript_path, self._transcript)
        self.clear_state_snapshot()
        self._save_metadata()

    def record_turn(
        self,
        *,
        model: str,
        duration_seconds: float,
        tool_count: int,
        error_count: int,
    ) -> None:
        turns = list(self._metadata.get("turns") or [])
        turns.append({
            "model": model,
            "duration_seconds": round(max(0.0, duration_seconds), 3),
            "tool_count": tool_count,
            "error_count": error_count,
            "completed_at": utc_now(),
        })
        self._metadata["turns"] = turns[-200:]
        self._metadata["updated_at"] = utc_now()
        self._save_metadata()

    def save_message_history(self, messages: list[Any], runtime: Any) -> None:
        self.message_history_path.write_bytes(ModelMessagesTypeAdapter.dump_json(messages, indent=2))
        ctx = getattr(runtime, "ctx", None)
        export_state = getattr(ctx, "export_state", None)
        if callable(export_state):
            try:
                state = export_state()
            except TypeError:
                state = None
            if state is not None:
                model_dump_json = getattr(state, "model_dump_json", None)
                with suppress(Exception):
                    if callable(model_dump_json):
                        state_json = model_dump_json(indent=2)
                        if isinstance(state_json, str):
                            self.context_state_path.write_text(state_json)
        self._metadata["updated_at"] = utc_now()
        self._save_metadata()

    def load_message_history(self) -> list[Any]:
        if not self.message_history_path.exists():
            return []
        return list(ModelMessagesTypeAdapter.validate_json(self.message_history_path.read_bytes()))

    def load_message_history_or_transcript(self) -> tuple[list[Any], bool]:
        entries = self.transcript()
        with suppress(Exception):
            messages = self.load_message_history()
            if messages and not _has_legacy_tool_markers(messages):
                return messages, False
        rebuilt = _message_history_from_transcript(entries)
        return rebuilt, bool(rebuilt)

    def restore_context_state(self, runtime: Any) -> bool:
        if not self.context_state_path.exists():
            return False
        ctx = getattr(runtime, "ctx", None)
        if ctx is None:
            return False
        state = ResumableState.model_validate_json(self.context_state_path.read_text())
        state.restore(ctx)
        return True

    def reset_context_state(self, runtime: Any) -> None:
        ctx = getattr(runtime, "ctx", None)
        if ctx is None:
            return
        ResumableState().restore(ctx)

    def transcript(self) -> list[dict[str, Any]]:
        if self._transcript:
            return list(self._transcript)
        return _message_history_transcript(self.message_history_path)

    def rename(self, name: str) -> None:
        self._metadata["name"] = _session_name(name)
        self._metadata["name_source"] = "explicit"
        self._metadata["updated_at"] = utc_now()
        self._save_metadata()

    def export_markdown(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = self._metadata
        lines = [
            f"# yaacli session {self.session_id}",
            "",
            f"- Name: {_session_name(metadata.get('name')) or '(unnamed)'}",
            f"- Model: {metadata.get('model') or self.model}",
            f"- Working dir: {metadata.get('working_dir') or self.working_dir}",
            f"- Updated: {metadata.get('updated_at') or ''}",
            "",
        ]
        for entry in self._transcript:
            kind = str(entry.get("kind") or "system")
            label = str(entry.get("label") or kind)
            text = str(entry.get("text") or "")
            lines.append(f"## {kind}: {label}")
            lines.append("")
            if kind == "tool":
                lines.append("```text")
                lines.append(text)
                lines.append("```")
            else:
                lines.append(text)
            lines.append("")
        path.write_text("\n".join(lines).rstrip() + "\n")
        return path

    def listings(self) -> list[SessionListing]:
        if not self.sessions_dir.exists():
            return []
        out: list[SessionListing] = []
        for directory in self.sessions_dir.iterdir():
            if not directory.is_dir():
                continue
            metadata = _read_json(directory / "metadata.json", {})
            first_user_prompt, latest_user_prompt = _transcript_user_prompts(directory / "transcript.json")
            if not first_user_prompt:
                projected = _message_history_transcript(directory / "message_history.json")
                projected_prompts = [
                    _session_name(entry.get("text"))
                    for entry in projected
                    if entry.get("kind") == "user" and not str(entry.get("text") or "").lstrip().startswith("/")
                ]
                if projected_prompts:
                    first_user_prompt = projected_prompts[0]
                    latest_user_prompt = projected_prompts[-1]
            out.append(
                SessionListing(
                    session_id=directory.name,
                    name=_session_name(metadata.get("name")) or first_user_prompt,
                    latest_user_prompt=(_session_name(metadata.get("latest_user_prompt")) or latest_user_prompt),
                    updated_at=str(metadata.get("updated_at") or ""),
                    working_dir=str(metadata.get("working_dir") or ""),
                    model=str(metadata.get("model") or ""),
                    path=directory,
                )
            )
        out.sort(key=lambda item: item.updated_at or "", reverse=True)
        return out

    def resolve_session_id(self, value: str) -> str | None:
        value = value.strip()
        listings = self.listings()
        if value in {"", "latest"}:
            return listings[0].session_id if listings else None
        exact = self.sessions_dir / value
        if exact.is_dir():
            return value
        matches = [item.session_id for item in listings if item.session_id.startswith(value)]
        return matches[0] if len(matches) == 1 else None

    def dump_to_folder(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        for source in (
            self.metadata_path,
            self.transcript_path,
            self.message_history_path,
            self.context_state_path,
        ):
            if source.exists():
                shutil.copy(source, folder / source.name)
        return folder

    def load_from_folder(self, folder: Path) -> None:
        for name in ("metadata.json", "transcript.json", "message_history.json", "context_state.json"):
            source = folder / name
            target = self.session_dir / name
            if source.exists():
                shutil.copy(source, target)
            else:
                with suppress(FileNotFoundError):
                    target.unlink()
        self.start()

    def _save_metadata(self) -> None:
        _write_json(self.metadata_path, self._metadata)

    def _prune_old_sessions(self) -> None:
        listings = self.listings()
        for item in listings[self.max_sessions :]:
            shutil.rmtree(item.path, ignore_errors=True)
