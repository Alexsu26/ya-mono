"""Tests for the YAACLI Desktop JSON Lines sidecar."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from yaacli.desktop.protocol import HandshakeEnvelope, ResponseEnvelope
from yaacli.desktop.sidecar import SidecarServer


def test_sidecar_handshake_advertises_protocol_and_commands() -> None:
    handshake = SidecarServer()._handshake()

    assert isinstance(handshake, HandshakeEnvelope)
    assert "workspace.open" in handshake.capabilities.commands
    assert "approval.requested" in handshake.capabilities.events


@pytest.mark.asyncio
async def test_sidecar_writes_handshake_before_loading_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    server = SidecarServer(defer_runtime=True)
    order: list[str] = []

    class Service:
        async def close(self) -> None:
            order.append("close")

    async def capture(envelope: Any) -> None:
        assert isinstance(envelope, HandshakeEnvelope)
        order.append("handshake")

    def initialize() -> None:
        order.append("runtime")
        server._service = Service()

    monkeypatch.setattr(server, "_write", capture)
    monkeypatch.setattr(server, "_initialize_runtime", initialize)
    server._shutdown.set()

    assert await server.run() == 0
    assert order == ["handshake", "runtime", "close"]


@pytest.mark.asyncio
async def test_sidecar_correlates_health_response(monkeypatch: pytest.MonkeyPatch) -> None:
    server = SidecarServer()
    written: list[Any] = []

    async def capture(envelope: Any) -> None:
        written.append(envelope)

    monkeypatch.setattr(server, "_write", capture)
    await server._handle_line(
        json.dumps({
            "protocol_version": 1,
            "type": "request",
            "request_id": "req-health",
            "command": "runtime.health",
            "payload": {},
        }).encode()
    )

    response = written[-1]
    assert isinstance(response, ResponseEnvelope)
    assert response.request_id == "req-health"
    assert response.ok is True


@pytest.mark.asyncio
async def test_sidecar_rejects_malformed_request(monkeypatch: pytest.MonkeyPatch) -> None:
    server = SidecarServer()
    written: list[Any] = []

    async def capture(envelope: Any) -> None:
        written.append(envelope)

    monkeypatch.setattr(server, "_write", capture)
    await server._handle_line(b"not-json")

    response = written[-1]
    assert isinstance(response, ResponseEnvelope)
    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "invalid_request"


@pytest.mark.asyncio
async def test_sidecar_session_round_trip(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    server = SidecarServer(config_dir=tmp_path / "config")

    opened = await server._dispatch("workspace.open", {"path": str(workspace)})
    created = await server._dispatch("session.create", {"name": "Desktop"})
    listed = await server._dispatch("session.list", {})

    assert opened["path"] == str(workspace.resolve())
    assert listed["sessions"][0]["id"] == created["session"]["id"]
    await server._service.close()
