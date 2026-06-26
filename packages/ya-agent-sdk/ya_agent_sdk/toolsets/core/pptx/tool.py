"""Agent-facing PPTX render tool."""

from __future__ import annotations

import tempfile
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, cast

from pydantic import Field
from pydantic_ai import RunContext
from ya_agent_environment import FileOperator

from ya_agent_sdk._logger import get_logger
from ya_agent_sdk.context import AgentContext
from ya_agent_sdk.toolsets.core.base import BaseTool
from ya_agent_sdk.toolsets.core.pptx.assets import search_public_images
from ya_agent_sdk.toolsets.core.pptx.renderer import render_pptx_with_node
from ya_agent_sdk.toolsets.core.pptx.schemas import AssetManifest, SlidePlan
from ya_agent_sdk.toolsets.core.pptx.templates import get_template_profile
from ya_agent_sdk.toolsets.core.pptx.validator import validate_pptx

logger = get_logger(__name__)


class PptxRenderTool(BaseTool):
    """Render an editable PowerPoint deck from a SlidePlan JSON payload."""

    name = "pptx_render"
    description = "Render an editable .pptx deck from a SlidePlan JSON payload and write it to the workspace."

    def is_available(self, ctx: RunContext[AgentContext]) -> bool:
        if ctx.deps.file_operator is None:
            logger.debug("PptxRenderTool unavailable: file_operator is not configured")
            return False
        return True

    async def call(
        self,
        ctx: RunContext[AgentContext],
        slide_plan_json: Annotated[str, Field(description="SlidePlan JSON string to render.")],
        output_file_name: Annotated[
            str,
            Field(description="Workspace-relative output PPTX path.", default="deck.pptx"),
        ] = "deck.pptx",
        template_scene: Annotated[
            str | None,
            Field(description="Optional template scene override.", default=None),
        ] = None,
        template_style: Annotated[
            str | None,
            Field(description="Optional template style override.", default=None),
        ] = None,
    ) -> dict[str, Any]:
        file_operator = cast(FileOperator, ctx.deps.file_operator)
        try:
            plan = SlidePlan.model_validate_json(slide_plan_json)
        except Exception as exc:
            return {"success": False, "error": f"Invalid SlidePlan JSON: {exc}"}

        output_path = PurePosixPath(output_file_name)
        if output_path.is_absolute() or ".." in output_path.parts:
            return {"success": False, "error": "output_file_name must be a safe workspace-relative path"}
        if output_path.suffix.lower() != ".pptx":
            output_path = output_path.with_suffix(".pptx")

        template = get_template_profile(template_scene or plan.scene, template_style or plan.style)
        assets = []
        for slide in plan.slides:
            for slot in slide.visual_slots:
                if slot.prompt and not slot.source_path:
                    assets.extend(await search_public_images(slot.prompt, limit=1))

        with tempfile.TemporaryDirectory() as local_tmp:
            tmp_dir = Path(local_tmp)
            local_output = tmp_dir / output_path.name
            render_plan = plan.model_copy(deep=True)
            local_asset_dir = tmp_dir / "assets"
            local_asset_dir.mkdir(parents=True, exist_ok=True)
            for slide in render_plan.slides:
                for slot_index, slot in enumerate(slide.visual_slots):
                    if not slot.source_path:
                        continue
                    source_path = PurePosixPath(slot.source_path)
                    if source_path.is_absolute() or ".." in source_path.parts:
                        return {"success": False, "error": "visual source_path must be a safe workspace-relative path"}
                    try:
                        asset_bytes = await file_operator.read_bytes(str(source_path))
                    except Exception as exc:
                        return {
                            "success": False,
                            "error": f"Could not read visual source_path {slot.source_path!r}: {exc}",
                        }
                    suffix = source_path.suffix or ".bin"
                    local_asset_path = local_asset_dir / f"slide-{slide.index}-slot-{slot_index}{suffix}"
                    local_asset_path.write_bytes(asset_bytes)
                    slot.source_path = str(local_asset_path)
            render_manifest = await render_pptx_with_node(
                plan=render_plan,
                template=template,
                assets=assets,
                output_path=local_output,
                work_dir=tmp_dir,
            )
            validation = validate_pptx(pptx_path=local_output, plan=plan, render_manifest=render_manifest)
            deck_bytes = local_output.read_bytes()
            render_manifest_json = render_manifest.model_dump_json(indent=2)
            asset_manifest_json = AssetManifest(assets=render_manifest.assets).model_dump_json(indent=2)

        output_dir = str(output_path.parent)
        if output_dir and output_dir != ".":
            await file_operator.mkdir(output_dir, parents=True)
        await file_operator.write_file(str(output_path), deck_bytes)

        manifest_path = output_path.with_name("render-manifest.json")
        asset_manifest_path = output_path.with_name("asset-manifest.json")
        await file_operator.write_file(str(manifest_path), render_manifest_json)
        await file_operator.write_file(str(asset_manifest_path), asset_manifest_json)

        return {
            "success": validation.success,
            "output_path": str(output_path),
            "manifest_path": str(manifest_path),
            "asset_manifest_path": str(asset_manifest_path),
            "validation": validation.model_dump(mode="json"),
        }
