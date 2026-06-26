"""Contract tests for YAACLI Desktop protocol models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from yaacli.desktop.protocol import (
    PROTOCOL_VERSION,
    EventEnvelope,
    HandshakeEnvelope,
    ProtocolCapabilities,
    RequestEnvelope,
    ResponseEnvelope,
)

FIXTURES = Path(__file__).parent / "fixtures" / "desktop_protocol"


def test_handshake_round_trip_is_strict_and_versioned() -> None:
    handshake = HandshakeEnvelope(
        runtime_version="0.1.0",
        capabilities=ProtocolCapabilities(commands=["runtime.health"], events=["runtime.health"]),
    )

    restored = HandshakeEnvelope.model_validate_json(handshake.model_dump_json())

    assert restored.protocol_version == PROTOCOL_VERSION
    assert restored.capabilities.max_message_bytes > 0


def test_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RequestEnvelope.model_validate({
            "protocol_version": PROTOCOL_VERSION,
            "type": "request",
            "request_id": "req-1",
            "command": "runtime.health",
            "payload": {},
            "unexpected": True,
        })


def test_event_sequence_must_not_be_negative() -> None:
    with pytest.raises(ValidationError):
        EventEnvelope(event="text.delta", run_id="run-1", sequence=-1)


def test_response_has_one_correlated_request_id() -> None:
    response = ResponseEnvelope(request_id="req-1", ok=True, payload={"status": "ready"})

    assert response.request_id == "req-1"
    assert response.error is None


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("handshake.json", HandshakeEnvelope),
        ("request.json", RequestEnvelope),
        ("event.json", EventEnvelope),
    ],
)
def test_shared_golden_fixtures(name: str, model: type[object]) -> None:
    payload = json.loads((FIXTURES / name).read_text())

    model.model_validate(payload)  # type: ignore[attr-defined]


def test_shared_incompatible_version_fixture_is_rejected() -> None:
    payload = json.loads((FIXTURES / "invalid-version.json").read_text())

    with pytest.raises(ValidationError):
        HandshakeEnvelope.model_validate(payload)
