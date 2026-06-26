"""PPTX generation tools and schemas."""

from ya_agent_sdk.toolsets.core.pptx.schemas import (
    AssetManifest,
    AssetRecord,
    PptRequestBrief,
    PptxValidationResult,
    RenderManifest,
    SlideLayout,
    SlidePlan,
    SlideSpec,
    SlideVisualSlot,
    TemplateLayout,
    TemplateProfile,
)
from ya_agent_sdk.toolsets.core.pptx.tool import PptxRenderTool

tools = [PptxRenderTool]

__all__ = [
    "AssetManifest",
    "AssetRecord",
    "PptRequestBrief",
    "PptxRenderTool",
    "PptxValidationResult",
    "RenderManifest",
    "SlideLayout",
    "SlidePlan",
    "SlideSpec",
    "SlideVisualSlot",
    "TemplateLayout",
    "TemplateProfile",
    "tools",
]
