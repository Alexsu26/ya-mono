from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from pydantic_ai import RunContext
from ya_agent_sdk.context import AgentContext
from ya_agent_sdk.environment.local import LocalEnvironment
from ya_agent_sdk.toolsets.core.pptx import tools
from ya_agent_sdk.toolsets.core.pptx.schemas import PptRequestBrief, SlidePlan, SlideSpec
from ya_agent_sdk.toolsets.core.pptx.tool import PptxRenderTool


def test_pptx_render_tool_exported() -> None:
    assert PptxRenderTool in tools


def test_pptx_render_tool_unavailable_without_file_operator(agent_context: AgentContext) -> None:
    tool = PptxRenderTool()
    mock_run_ctx = MagicMock(spec=RunContext)
    mock_run_ctx.deps = SimpleNamespace(file_operator=None)

    assert tool.is_available(mock_run_ctx) is False


async def test_pptx_render_tool_writes_workspace_outputs(tmp_path: Path) -> None:
    plan = SlidePlan(
        brief=PptRequestBrief(topic="Demo", purpose="demo"),
        scene="simple_formal",
        style="simple_formal",
        slides=[SlideSpec(index=1, role="cover", title="Demo", must_keep_text=["Demo"])],
    )

    async with AsyncExitStack() as stack:
        env = await stack.enter_async_context(
            LocalEnvironment(allowed_paths=[tmp_path], default_path=tmp_path, tmp_base_dir=tmp_path)
        )
        ctx = await stack.enter_async_context(AgentContext(env=env))
        mock_run_ctx = MagicMock(spec=RunContext)
        mock_run_ctx.deps = ctx

        result = await PptxRenderTool().call(
            mock_run_ctx,
            slide_plan_json=plan.model_dump_json(),
            output_file_name="demo/deck.pptx",
        )

    assert result["success"] is True
    assert result["output_path"] == "demo/deck.pptx"
    assert result["manifest_path"] == "demo/render-manifest.json"
    assert result["validation"]["success"] is True
    assert (tmp_path / "demo" / "deck.pptx").exists()
    assert (tmp_path / "demo" / "render-manifest.json").exists()
    assert (tmp_path / "demo" / "asset-manifest.json").exists()


async def test_pptx_render_tool_reports_empty_business_plan_as_failed(tmp_path: Path) -> None:
    plan = SlidePlan(
        brief=PptRequestBrief(topic="Business proposal", purpose="proposal"),
        scene="business_proposal",
        style="consulting_report",
        slides=[
            SlideSpec(index=1, role="cover", title="Business proposal"),
            SlideSpec(index=2, role="content", title="SWOT analysis"),
        ],
    )

    async with AsyncExitStack() as stack:
        env = await stack.enter_async_context(
            LocalEnvironment(allowed_paths=[tmp_path], default_path=tmp_path, tmp_base_dir=tmp_path)
        )
        ctx = await stack.enter_async_context(AgentContext(env=env))
        mock_run_ctx = MagicMock(spec=RunContext)
        mock_run_ctx.deps = ctx

        result = await PptxRenderTool().call(
            mock_run_ctx,
            slide_plan_json=plan.model_dump_json(),
            output_file_name="demo/empty.pptx",
        )

    assert result["success"] is False
    assert "Slide 2 'SWOT analysis' has no body blocks or visual slots" in result["validation"]["warnings"]


async def test_pptx_render_tool_maps_workspace_visual_source_paths(tmp_path: Path) -> None:
    image_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?"
        b"\x00\x05\xfe\x02\xfeA\x8d\xec\x8c\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (tmp_path / "ppt-inputs").mkdir()
    (tmp_path / "ppt-inputs" / "cover.png").write_bytes(image_bytes)
    plan = SlidePlan(
        brief=PptRequestBrief(topic="Business proposal", purpose="proposal"),
        scene="business_proposal",
        style="consulting_report",
        slides=[
            SlideSpec(
                index=1,
                role="cover",
                layout="hero_image",
                title="Business proposal",
                body_blocks=["Source-grounded context"],
                visual_slots=[
                    {
                        "name": "site photo",
                        "kind": "image",
                        "source_path": "ppt-inputs/cover.png",
                    }
                ],
            ),
            SlideSpec(index=2, role="summary", title="Recommendation", body_blocks=["Proceed with staged launch"]),
        ],
    )

    async with AsyncExitStack() as stack:
        env = await stack.enter_async_context(
            LocalEnvironment(allowed_paths=[tmp_path], default_path=tmp_path, tmp_base_dir=tmp_path)
        )
        ctx = await stack.enter_async_context(AgentContext(env=env))
        mock_run_ctx = MagicMock(spec=RunContext)
        mock_run_ctx.deps = ctx

        result = await PptxRenderTool().call(
            mock_run_ctx,
            slide_plan_json=plan.model_dump_json(),
            output_file_name="demo/with-image.pptx",
        )

    assert result["success"] is True
    assert (tmp_path / "demo" / "with-image.pptx").exists()
