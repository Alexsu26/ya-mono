"""Characterization tests for the shared YAACLI stream boundary."""

from __future__ import annotations

from unittest.mock import MagicMock

from yaacli.config import GeneralConfig, YaacliConfig
from yaacli.execution import open_runtime_stream


def test_open_runtime_stream_applies_shared_recovery_and_usage_options(monkeypatch: object) -> None:
    from yaacli import execution

    stream = object()
    captured: dict[str, object] = {}

    def fake_stream_agent(runtime: object, **kwargs: object) -> object:
        captured["runtime"] = runtime
        captured.update(kwargs)
        return stream

    monkeypatch.setattr(execution, "stream_agent", fake_stream_agent)  # type: ignore[attr-defined]
    config = YaacliConfig(
        general=GeneralConfig(
            model="openai-chat:gpt-4",
            max_requests=7,
            agent_stream_resume_on_error=True,
            agent_stream_resume_max_attempts=3,
            agent_stream_resume_prompt="continue safely",
        )
    )
    runtime = MagicMock()

    result = open_runtime_stream(
        runtime,
        config,
        user_prompt="hello",
        message_history=["prior"],
        emit_lifecycle_events=False,
    )

    assert result is stream
    assert captured["runtime"] is runtime
    assert captured["user_prompt"] == "hello"
    assert captured["message_history"] == ["prior"]
    assert captured["resume_on_error"] is True
    assert captured["resume_max_attempts"] == 3
    assert captured["resume_prompt"] == "continue safely"
    assert captured["emit_lifecycle_events"] is False
    assert captured["usage_limits"].request_limit == 7  # type: ignore[union-attr]


def test_open_runtime_stream_forwards_deferred_results(monkeypatch: object) -> None:
    from yaacli import execution

    captured: dict[str, object] = {}

    def fake_stream_agent(_runtime: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(execution, "stream_agent", fake_stream_agent)  # type: ignore[attr-defined]
    config = YaacliConfig(general=GeneralConfig(model="openai-chat:gpt-4"))
    deferred = MagicMock()

    open_runtime_stream(MagicMock(), config, deferred_tool_results=deferred)

    assert captured["deferred_tool_results"] is deferred
    assert captured["user_prompt"] is None
