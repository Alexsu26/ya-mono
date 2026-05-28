"""Tests for yaacli headless print mode."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from pydantic_ai import DeferredToolRequests
from yaacli.cli import cli
from yaacli.config import GeneralConfig, YaacliConfig


class DummyAsyncContext:
    """Small async context helper for mocked runtime/browser/stream objects."""

    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *_args: object) -> None:
        return None


class EmptyStream:
    """Async iterable with a final run result but no emitted events."""

    def __init__(self, output: object) -> None:
        self.run = SimpleNamespace(result=SimpleNamespace(output=output))

    def __aiter__(self) -> EmptyStream:
        return self

    async def __anext__(self) -> object:
        raise StopAsyncIteration


def configured() -> YaacliConfig:
    return YaacliConfig(general=GeneralConfig(model="openai-chat:gpt-4"))


def test_cli_headless_option_exists() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "-P, --print" in result.output


def test_cli_headless_prompt_argument_runs_without_tui(tmp_path: Path) -> None:
    runner = CliRunner()
    calls: list[str] = []

    async def fake_run_headless(*_args: object, prompt: str, **_kwargs: object) -> str:
        calls.append(prompt)
        return "final answer"

    with (
        patch("yaacli.cli.ConfigManager.load", return_value=configured()),
        patch("yaacli.cli.ensure_builtin_assets"),
        patch("yaacli.cli.load_env_from_config"),
        patch("yaacli.cli._run_tui", side_effect=AssertionError("TUI should not start")),
        patch("yaacli.cli._run_headless", side_effect=fake_run_headless),
    ):
        result = runner.invoke(cli, ["-P", "hello", "world"])

    assert result.exit_code == 0
    assert result.output == "final answer\n"
    assert calls == ["hello world"]


def test_cli_headless_reads_prompt_from_stdin() -> None:
    runner = CliRunner()
    calls: list[str] = []

    async def fake_run_headless(*_args: object, prompt: str, **_kwargs: object) -> str:
        calls.append(prompt)
        return "stdin answer"

    with (
        patch("yaacli.cli.ConfigManager.load", return_value=configured()),
        patch("yaacli.cli.ensure_builtin_assets"),
        patch("yaacli.cli.load_env_from_config"),
        patch("yaacli.cli._run_headless", side_effect=fake_run_headless),
    ):
        result = runner.invoke(cli, ["--print"], input="hello from stdin\n")

    assert result.exit_code == 0
    assert result.output == "stdin answer\n"
    assert calls == ["hello from stdin"]


def test_cli_headless_requires_prompt_or_stdin() -> None:
    runner = CliRunner()

    with (
        patch("yaacli.cli.ConfigManager.load", return_value=configured()),
        patch("yaacli.cli.ensure_builtin_assets"),
        patch("yaacli.cli.load_env_from_config"),
    ):
        result = runner.invoke(cli, ["-P"], input="")

    assert result.exit_code != 0
    assert "Headless mode requires a prompt argument or stdin input" in result.output


def test_cli_headless_unconfigured_does_not_start_setup_wizard() -> None:
    runner = CliRunner()

    with (
        patch("yaacli.cli.ConfigManager.load", return_value=YaacliConfig()),
        patch("yaacli.cli.ensure_builtin_assets"),
        patch("yaacli.cli.run_setup_wizard", side_effect=AssertionError("setup wizard should not start")),
    ):
        result = runner.invoke(cli, ["-P", "hello"])

    assert result.exit_code != 0
    assert "yaacli is not configured" in result.output


def test_cli_prompt_arguments_require_headless_mode() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["hello"])

    assert result.exit_code != 0
    assert "Prompt arguments require -P/--print" in result.output


@pytest.mark.asyncio
async def test_run_headless_returns_final_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from yaacli import headless

    stream_calls: list[dict[str, object]] = []
    config_manager = MagicMock()
    config_manager.load_mcp_config.return_value = None
    config_manager.config_dir = tmp_path / "config"

    def fake_stream_agent(runtime: object, user_prompt: str, **kwargs: object) -> DummyAsyncContext:
        stream_calls.append({"runtime": runtime, "prompt": user_prompt, "kwargs": kwargs})
        return DummyAsyncContext(EmptyStream("final output"))

    monkeypatch.setattr(headless, "BrowserManager", lambda *_args, **_kwargs: DummyAsyncContext("browser"))
    monkeypatch.setattr(headless, "create_tui_runtime", lambda **_kwargs: "runtime")
    monkeypatch.setattr(headless, "stream_agent", fake_stream_agent)

    output = await headless.run_headless(
        configured(),
        config_manager,
        prompt="hello",
        working_dir=tmp_path,
    )

    assert output == "final output"
    assert stream_calls[0]["prompt"] == "hello"
    assert stream_calls[0]["kwargs"]["emit_lifecycle_events"] is False


@pytest.mark.asyncio
async def test_run_headless_rejects_deferred_tool_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yaacli import headless

    config_manager = MagicMock()
    config_manager.load_mcp_config.return_value = None
    config_manager.config_dir = tmp_path / "config"

    monkeypatch.setattr(headless, "BrowserManager", lambda *_args, **_kwargs: DummyAsyncContext("browser"))
    monkeypatch.setattr(headless, "create_tui_runtime", lambda **_kwargs: "runtime")
    monkeypatch.setattr(
        headless,
        "stream_agent",
        lambda *_args, **_kwargs: DummyAsyncContext(EmptyStream(DeferredToolRequests())),
    )

    with pytest.raises(headless.HeadlessExecutionError, match="interactive tool approvals"):
        await headless.run_headless(
            configured(),
            config_manager,
            prompt="needs approval",
            working_dir=tmp_path,
        )
