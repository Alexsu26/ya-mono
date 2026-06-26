"""JSON Lines process entry point for the YAACLI Desktop sidecar."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from yaacli.desktop.api import DesktopRuntimeError
from yaacli.desktop.protocol import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    SUPPORTED_COMMANDS,
    SUPPORTED_EVENTS,
    ApprovalDecision,
    ErrorInfo,
    EventEnvelope,
    HandshakeEnvelope,
    InputPart,
    ProtocolCapabilities,
    RequestEnvelope,
    ResponseEnvelope,
)


class SidecarServer:
    """Read commands from stdin and serialize all protocol output to stdout."""

    def __init__(
        self,
        *,
        workspace: Path | None = None,
        config_dir: Path | None = None,
        defer_runtime: bool = False,
    ) -> None:
        self._initial_workspace = workspace
        self._config_dir = config_dir
        self._write_lock = asyncio.Lock()
        self._shutdown = asyncio.Event()
        self._service: Any = None
        if not defer_runtime:
            self._initialize_runtime()

    async def run(self) -> int:
        await self._write(self._handshake())
        self._initialize_runtime()
        if self._initial_workspace is not None:
            try:
                await self._service.open_workspace(str(self._initial_workspace))
            except DesktopRuntimeError as exc:
                await self.emit_event(
                    EventEnvelope(event="runtime.health", payload={"status": "unavailable", "message": str(exc)})
                )
        try:
            while not self._shutdown.is_set():
                line = await asyncio.to_thread(sys.stdin.buffer.readline, MAX_MESSAGE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_MESSAGE_BYTES:
                    await self._write(
                        ResponseEnvelope(
                            request_id="oversized-message",
                            ok=False,
                            error=ErrorInfo(
                                code="message_too_large", message="Protocol message exceeds the size limit"
                            ),
                        )
                    )
                    continue
                await self._handle_line(line)
        finally:
            if self._service is not None:
                await self._service.close()
        return 0

    def _initialize_runtime(self) -> None:
        if self._service is not None:
            return
        from yaacli.desktop.runtime import DesktopRuntimeService

        self._service = DesktopRuntimeService(self.emit_event, config_dir=self._config_dir)

    async def emit_event(self, event: EventEnvelope) -> None:
        await self._write(event)

    async def _handle_line(self, line: bytes) -> None:
        request_id = "invalid-request"
        try:
            data = json.loads(line)
            if isinstance(data, dict) and isinstance(data.get("request_id"), str):
                request_id = data["request_id"]
            request = RequestEnvelope.model_validate(data)
            payload = await self._dispatch(request.command, request.payload)
            response = ResponseEnvelope(request_id=request.request_id, ok=True, payload=payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            response = ResponseEnvelope(
                request_id=request_id,
                ok=False,
                error=ErrorInfo(code="invalid_request", message=str(exc)),
            )
        except DesktopRuntimeError as exc:
            response = ResponseEnvelope(
                request_id=request_id,
                ok=False,
                error=ErrorInfo(code=exc.code, message=str(exc), retryable=exc.retryable),
            )
        except Exception as exc:
            print(f"Unhandled sidecar command error: {type(exc).__name__}: {exc}", file=sys.stderr)
            response = ResponseEnvelope(
                request_id=request_id,
                ok=False,
                error=ErrorInfo(code="internal_error", message="The desktop runtime could not complete the command"),
            )
        await self._write(response)

    async def _dispatch(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command == "runtime.health":
            return await self._service.health()
        if command == "workspace.open":
            return await self._service.open_workspace(str(payload["path"]))
        if command == "session.create":
            return (await self._service.create_session(str(payload.get("name") or ""))).model_dump(mode="json")
        if command == "session.list":
            return {"sessions": [item.model_dump(mode="json") for item in await self._service.list_sessions()]}
        if command == "session.list_archived":
            return {"sessions": [item.model_dump(mode="json") for item in await self._service.list_archived_sessions()]}
        if command == "session.load":
            return (await self._service.load_session(str(payload["session_id"]))).model_dump(mode="json")
        if command == "session.rename":
            return (await self._service.rename_session(str(payload["session_id"]), str(payload["name"]))).model_dump(
                mode="json"
            )
        if command == "session.archive":
            await self._service.archive_session(str(payload["session_id"]))
            return {}
        if command == "session.restore":
            return (await self._service.restore_session(str(payload["session_id"]))).model_dump(mode="json")
        if command == "run.start":
            parts = [InputPart.model_validate(item) for item in payload.get("input_parts", [])]
            run_id = await self._service.start_run(str(payload["session_id"]), parts)
            return {"run_id": run_id}
        if command == "run.cancel":
            await self._service.cancel_run(str(payload["run_id"]))
            return {}
        if command == "run.steer":
            await self._service.steer_run(str(payload["run_id"]), str(payload["text"]))
            return {}
        if command == "approval.resolve":
            await self._service.resolve_approval(
                str(payload["approval_id"]),
                str(payload["workspace_id"]),
                str(payload["session_id"]),
                str(payload["run_id"]),
                ApprovalDecision(str(payload["decision"])),
                str(payload["reason"]) if payload.get("reason") else None,
            )
            return {}
        if command == "config.get":
            return await self._service.config_snapshot()
        if command == "config.update":
            return await self._service.update_config(
                active_profile=str(payload["active_profile"]) if payload.get("active_profile") else None,
                theme=str(payload["theme"]) if payload.get("theme") else None,
            )
        if command == "runtime.shutdown":
            self._shutdown.set()
            return {}
        raise DesktopRuntimeError("unknown_command", f"Unknown command: {command}")

    async def _write(self, envelope: Any) -> None:
        encoded = envelope.model_dump_json(exclude_none=True).encode() + b"\n"
        async with self._write_lock:
            sys.stdout.buffer.write(encoded)
            sys.stdout.buffer.flush()

    def _handshake(self) -> HandshakeEnvelope:
        try:
            runtime_version = version("yaacli")
        except PackageNotFoundError:
            runtime_version = "0.0.0+workspace"
        return HandshakeEnvelope(
            protocol_version=PROTOCOL_VERSION,
            runtime_version=runtime_version,
            capabilities=ProtocolCapabilities(commands=SUPPORTED_COMMANDS, events=SUPPORTED_EVENTS),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YAACLI Desktop sidecar")
    parser.add_argument("--workspace", type=Path, help="Initial workspace directory")
    parser.add_argument("--config-dir", type=Path, help="Override global YAACLI config directory")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    server = SidecarServer(workspace=args.workspace, config_dir=args.config_dir, defer_runtime=True)
    raise SystemExit(asyncio.run(server.run()))


if __name__ == "__main__":
    main()
