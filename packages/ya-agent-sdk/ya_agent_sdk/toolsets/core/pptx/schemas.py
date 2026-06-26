"""PPTX planning, rendering, and validation schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

PptScene = Literal["teaching_lesson", "work_report", "business_proposal", "simple_formal"]
PptStyle = Literal[
    "campus_clean",
    "modern_business",
    "consulting_report",
    "legacy_consulting_report",
    "editorial_park",
    "simple_formal",
]
SlideRole = Literal[
    "cover",
    "agenda",
    "section",
    "content",
    "case",
    "image_placeholder",
    "summary",
]
VisualSlotKind = Literal["image", "background", "icon", "video_placeholder", "shape"]
SlideLayout = Literal[
    "default",
    "hero_image",
    "metric_cards",
    "matrix_2x2",
    "risk_grid",
    "timeline",
    "two_column",
    "hub_spoke",
    "party_roles",
]


class PptRequestBrief(BaseModel):
    topic: str
    audience: str | None = None
    purpose: str
    tone: str = "professional"
    expected_slide_count: int | None = None
    hard_requirements: list[str] = Field(default_factory=list)
    missing_placeholders: list[str] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)


class SlideVisualSlot(BaseModel):
    name: str
    kind: VisualSlotKind
    prompt: str | None = None
    source_path: str | None = None
    placeholder_text: str | None = None


class SlideSpec(BaseModel):
    index: int
    role: SlideRole
    title: str
    layout: SlideLayout = "default"
    subtitle: str | None = None
    body_blocks: list[str] = Field(default_factory=list)
    visual_slots: list[SlideVisualSlot] = Field(default_factory=list)
    speaker_notes: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    must_keep_text: list[str] = Field(default_factory=list)
    placeholder_items: list[str] = Field(default_factory=list)


class SlidePlan(BaseModel):
    brief: PptRequestBrief
    scene: PptScene
    style: PptStyle
    slides: list[SlideSpec]

    @model_validator(mode="after")
    def reject_duplicate_slide_indexes(self) -> SlidePlan:
        indexes = [slide.index for slide in self.slides]
        if len(indexes) != len(set(indexes)):
            raise ValueError("slide indexes must be unique")
        return self


class TemplateLayout(BaseModel):
    id: str
    role: SlideRole | None = None
    description: str | None = None
    slots: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class TemplateProfile(BaseModel):
    id: str
    scene: PptScene
    style: PptStyle
    keywords: list[str] = Field(default_factory=list)
    layouts: list[TemplateLayout] = Field(default_factory=list)
    theme: dict[str, Any] = Field(default_factory=dict)
    asset_policy: dict[str, Any] = Field(default_factory=dict)


class AssetRecord(BaseModel):
    id: str | None = None
    source: str
    kind: str = "image"
    title: str | None = None
    query: str | None = None
    url: str | None = None
    thumbnail_url: str | None = None
    local_path: str | None = None
    author: str | None = None
    license: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetManifest(BaseModel):
    assets: list[AssetRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RenderManifest(BaseModel):
    output_path: str
    manifest_path: str | None = None
    slide_count: int
    renderer: str = "ya-pptx-renderer"
    assets: list[AssetRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PptxValidationResult(BaseModel):
    success: bool
    slide_count: int = 0
    missing_text: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
