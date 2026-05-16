"""Headless execution support for yaacli."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import DeferredToolRequests, UsageLimits
from ya_agent_sdk.agents.main import stream_agent

from yaacli.browser import BrowserManager
from yaacli.config import ConfigManager, YaacliConfig
from yaacli.hooks import emit_context_update
from yaacli.logging import get_logger
from yaacli.runtime import create_tui_runtime

logger = get_logger(__name__)


class HeadlessExecutionError(RuntimeError):
    """Raised when headless mode cannot complete non-interactively."""


async def run_headless(
    config: YaacliConfig,
    config_manager: ConfigManager,
    *,
    prompt: str,
    working_dir: Path | None = None,
) -> str:
    """Run one non-interactive agent turn and return the final model output."""
    async with BrowserManager(config.browser) as browser:
        runtime: Any = create_tui_runtime(
            config=config,
            mcp_config=config_manager.load_mcp_config(),
            browser_manager=browser,
            working_dir=working_dir,
            config_dir=config_manager.config_dir,
        )
        async with stream_agent(
            runtime,
            user_prompt=prompt,
            usage_limits=UsageLimits(request_limit=config.general.max_requests),
            post_node_hook=emit_context_update,
            resume_on_error=config.general.agent_stream_resume_on_error,
            resume_max_attempts=config.general.agent_stream_resume_max_attempts,
            resume_prompt=config.general.agent_stream_resume_prompt,
            emit_lifecycle_events=False,
        ) as stream:
            async for _event in stream:
                pass

            run = getattr(stream, "run", None)
            result = getattr(run, "result", None) if run is not None else None
            output: Any = getattr(result, "output", None) if result is not None else None

    if isinstance(output, DeferredToolRequests):
        raise HeadlessExecutionError(
            "Headless mode cannot handle interactive tool approvals. "
            "Run yaacli without -P/--print, or adjust tool approval settings."
        )

    if output is None:
        logger.debug("Headless run completed without a final output")
        return ""

    return str(output)
