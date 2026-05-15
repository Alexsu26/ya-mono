"""Local transcript persistence for the Textual console."""

from __future__ import annotations

import json
import shutil
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelMessagesTypeAdapter
from ya_agent_sdk.context import ResumableState


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
    ) -> None:
        if not text and kind != "tool":
            return
        self._transcript.append({
            "kind": kind,
            "label": label,
            "text": text,
            "error": error,
            "created_at": utc_now(),
        })
        if kind == "tool":
            self._metadata["tool_count"] = int(self._metadata.get("tool_count", 0)) + 1
        if error or kind == "error":
            self._metadata["error_count"] = int(self._metadata.get("error_count", 0)) + 1
        if kind == "user":
            prompt = _session_name(text)
            if prompt and not prompt.lstrip().startswith("/"):
                self._metadata["latest_user_prompt"] = prompt
                if (
                    not _session_name(self._metadata.get("name"))
                    and self._metadata.get("name_source") != "explicit"
                ):
                    self._metadata["name"] = prompt
                    self._metadata["name_source"] = "auto"
        self._metadata["updated_at"] = utc_now()
        _write_json(self.transcript_path, self._transcript)
        self._save_metadata()

    def clear_transcript(self) -> None:
        self._transcript = []
        self._metadata["latest_user_prompt"] = ""
        if self._metadata.get("name_source") == "auto":
            self._metadata["name"] = ""
            self._metadata["name_source"] = ""
        self._metadata["updated_at"] = utc_now()
        _write_json(self.transcript_path, self._transcript)
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
        self.message_history_path.write_bytes(
            ModelMessagesTypeAdapter.dump_json(messages, indent=2)
        )
        ctx = getattr(runtime, "ctx", None)
        export_state = getattr(ctx, "export_state", None)
        if callable(export_state):
            try:
                state = export_state()
            except TypeError:
                state = None
            if state is not None:
                with suppress(Exception):
                    self.context_state_path.write_text(state.model_dump_json(indent=2))
        self._metadata["updated_at"] = utc_now()
        self._save_metadata()

    def load_message_history(self) -> list[Any]:
        if not self.message_history_path.exists():
            return []
        return list(ModelMessagesTypeAdapter.validate_json(self.message_history_path.read_bytes()))

    def restore_context_state(self, runtime: Any) -> None:
        if not self.context_state_path.exists():
            return
        ctx = getattr(runtime, "ctx", None)
        if ctx is None:
            return
        state = ResumableState.model_validate_json(self.context_state_path.read_text())
        state.restore(ctx)

    def transcript(self) -> list[dict[str, Any]]:
        return list(self._transcript)

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
            first_user_prompt, latest_user_prompt = _transcript_user_prompts(
                directory / "transcript.json"
            )
            out.append(SessionListing(
                session_id=directory.name,
                name=_session_name(metadata.get("name")) or first_user_prompt,
                latest_user_prompt=(
                    _session_name(metadata.get("latest_user_prompt")) or latest_user_prompt
                ),
                updated_at=str(metadata.get("updated_at") or ""),
                working_dir=str(metadata.get("working_dir") or ""),
                model=str(metadata.get("model") or ""),
                path=directory,
            ))
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
            if source.exists():
                shutil.copy(source, self.session_dir / name)
        self.start()

    def _save_metadata(self) -> None:
        _write_json(self.metadata_path, self._metadata)

    def _prune_old_sessions(self) -> None:
        listings = self.listings()
        for item in listings[self.max_sessions:]:
            shutil.rmtree(item.path, ignore_errors=True)
