"""Lightweight deterministic PPTX validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pptx import Presentation

from ya_agent_sdk.toolsets.core.pptx.schemas import PptxValidationResult, RenderManifest, SlidePlan

CONTENT_REQUIRED_ROLES = {"agenda", "content", "case", "summary"}
BUSINESS_CONSULTING_MIN_SLIDES = 8
BUSINESS_CONSULTING_REQUIRED_LAYOUTS = {
    "section": "Business proposal consulting_report decks should include at least one section slide",
    "hub_spoke": "Business proposal consulting_report decks should include a hub_spoke ecosystem/system slide",
    "party_roles": "Business proposal consulting_report decks should include a party_roles cooperation/workstream slide",
}
BUSINESS_CONSULTING_MIN_LAYOUTS = 5
BUSINESS_CONSULTING_MIN_TEXT_PT = 12
BUSINESS_CONSULTING_MIN_MEDIAN_TEXT_PT = 14
BUSINESS_CONSULTING_MAX_SLIDE_CHARS = 520
BUSINESS_CONSULTING_MAX_BODY_BLOCKS = 8


def _shape_texts(shape) -> list[str]:
    texts: list[str] = []
    if hasattr(shape, "text") and shape.text:
        texts.append(shape.text)
    if hasattr(shape, "shapes"):
        for child in shape.shapes:
            texts.extend(_shape_texts(child))
    return texts


def _validate_business_consulting_plan(plan: SlidePlan) -> list[str]:
    if plan.scene != "business_proposal" or plan.style != "consulting_report":
        return []
    if len(plan.slides) < BUSINESS_CONSULTING_MIN_SLIDES:
        return []

    warnings: list[str] = []
    layouts = [slide.layout if slide.layout != "default" else slide.role for slide in plan.slides]
    layout_set = set(layouts)
    for layout, message in BUSINESS_CONSULTING_REQUIRED_LAYOUTS.items():
        if layout not in layout_set:
            warnings.append(message)

    if len(layout_set) < BUSINESS_CONSULTING_MIN_LAYOUTS:
        warnings.append(
            "Business proposal consulting_report deck is too repetitive: use at least "
            f"{BUSINESS_CONSULTING_MIN_LAYOUTS} distinct layout rhythms"
        )

    repeated_layout_count = sum(layout in {"metric_cards", "matrix_2x2"} for layout in layouts)
    content_slide_count = sum(slide.role in CONTENT_REQUIRED_ROLES or slide.role == "section" for slide in plan.slides)
    if content_slide_count and repeated_layout_count / content_slide_count >= 0.55:
        warnings.append(
            "Business proposal consulting_report deck is too repetitive: avoid relying mostly on metric_cards "
            "and matrix_2x2"
        )

    for slide in plan.slides:
        body_chars = sum(len(block) for block in slide.body_blocks)
        if body_chars > BUSINESS_CONSULTING_MAX_SLIDE_CHARS:
            warnings.append(
                f"Slide {slide.index} {slide.title!r} is too text-dense for a consulting_report slide: "
                f"{body_chars} body characters"
            )
        if len(slide.body_blocks) > BUSINESS_CONSULTING_MAX_BODY_BLOCKS:
            warnings.append(
                f"Slide {slide.index} {slide.title!r} has too many body blocks for presentation-grade layout"
            )

    return warnings


def _iter_font_sizes(presentation: Any) -> list[float]:
    sizes: list[float] = []
    for slide in presentation.slides:
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            for paragraph in shape.text_frame.paragraphs:
                for run in paragraph.runs:
                    if run.font.size is not None:
                        sizes.append(float(run.font.size.pt))
    return sizes


def _validate_business_consulting_visual_quality(
    *,
    plan: SlidePlan,
    presentation: Any,
    render_manifest: RenderManifest | None,
) -> list[str]:
    if plan.scene != "business_proposal" or plan.style != "consulting_report":
        return []
    if len(plan.slides) < BUSINESS_CONSULTING_MIN_SLIDES:
        return []

    warnings: list[str] = []
    template_assets = [
        asset
        for asset in (render_manifest.assets if render_manifest is not None else [])
        if asset.kind == "template_background" or asset.source == "template"
    ]
    if not template_assets:
        warnings.append("Business proposal consulting_report decks must use template-backed visual assets")

    font_sizes = sorted(_iter_font_sizes(presentation))
    if font_sizes:
        min_size = font_sizes[0]
        median_size = font_sizes[len(font_sizes) // 2]
        if min_size < BUSINESS_CONSULTING_MIN_TEXT_PT:
            warnings.append(
                "Business proposal consulting_report deck contains text below "
                f"{BUSINESS_CONSULTING_MIN_TEXT_PT}pt: minimum is {min_size:.1f}pt"
            )
        if median_size < BUSINESS_CONSULTING_MIN_MEDIAN_TEXT_PT:
            warnings.append(
                "Business proposal consulting_report deck has overly small typography: "
                f"median text size is {median_size:.1f}pt"
            )
    return warnings


def validate_pptx(
    *,
    pptx_path: Path,
    plan: SlidePlan,
    render_manifest: RenderManifest | None = None,
) -> PptxValidationResult:
    warnings: list[str] = []
    try:
        presentation = Presentation(str(pptx_path))
    except Exception as exc:
        return PptxValidationResult(success=False, warnings=[f"Could not parse PPTX: {exc}"])

    slide_count = len(presentation.slides)
    if slide_count != len(plan.slides):
        warnings.append(f"Expected {len(plan.slides)} slides, found {slide_count}")

    deck_text = "\n".join(
        text for slide in presentation.slides for shape in slide.shapes for text in _shape_texts(shape)
    )
    required_text: list[str] = []
    warnings.extend(_validate_business_consulting_plan(plan))
    warnings.extend(
        _validate_business_consulting_visual_quality(
            plan=plan,
            presentation=presentation,
            render_manifest=render_manifest,
        )
    )
    for slide in plan.slides:
        required_text.extend(slide.must_keep_text)
        required_text.extend(slide.placeholder_items)
        if slide.role in CONTENT_REQUIRED_ROLES and not slide.body_blocks and not slide.visual_slots:
            warnings.append(f"Slide {slide.index} {slide.title!r} has no body blocks or visual slots")
    missing_text = [text for text in required_text if text not in deck_text]

    return PptxValidationResult(
        success=not missing_text and not warnings,
        slide_count=slide_count,
        missing_text=missing_text,
        warnings=warnings,
    )
