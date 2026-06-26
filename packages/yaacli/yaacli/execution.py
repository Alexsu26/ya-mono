"""UI-independent YAACLI agent stream construction."""

from __future__ import annotations

from typing import Any

from pydantic_ai import UsageLimits
from ya_agent_sdk.agents.main import stream_agent

from yaacli.config import YaacliConfig
from yaacli.hooks import emit_context_update


def open_runtime_stream(
    runtime: Any,
    config: YaacliConfig,
    *,
    user_prompt: Any = None,
    message_history: list[Any] | None = None,
    deferred_tool_results: Any = None,
    emit_lifecycle_events: bool = True,
) -> Any:
    """Open a configured agent stream for any YAACLI presentation adapter."""
    return stream_agent(
        runtime,
        user_prompt=user_prompt,
        message_history=message_history,
        deferred_tool_results=deferred_tool_results,
        usage_limits=UsageLimits(request_limit=config.general.max_requests),
        post_node_hook=emit_context_update,
        resume_on_error=config.general.agent_stream_resume_on_error,
        resume_max_attempts=config.general.agent_stream_resume_max_attempts,
        resume_prompt=config.general.agent_stream_resume_prompt,
        emit_lifecycle_events=emit_lifecycle_events,
    )
