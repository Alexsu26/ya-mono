from __future__ import annotations

import pytest
from pydantic import ValidationError
from ya_agent_sdk.toolsets.core.pptx.schemas import PptRequestBrief, SlidePlan, SlideSpec


def test_slide_plan_accepts_mvp_roles() -> None:
    plan = SlidePlan(
        brief=PptRequestBrief(
            topic="Hot search fact checking",
            purpose="class lesson",
            expected_slide_count=2,
        ),
        scene="teaching_lesson",
        style="campus_clean",
        slides=[
            SlideSpec(index=1, role="cover", title="Hot Search"),
            SlideSpec(
                index=2,
                role="summary",
                title="Summary",
                body_blocks=["Check source first"],
            ),
        ],
    )

    assert plan.slides[0].role == "cover"
    assert plan.brief.expected_slide_count == 2


def test_slide_spec_preserves_missing_data_placeholders() -> None:
    slide = SlideSpec(
        index=1,
        role="content",
        title="2025 Core Performance",
        body_blocks=["Completed [please fill: shipment count] nominated cargo cases"],
        placeholder_items=["[please fill: shipment count]"],
    )

    assert "[please fill: shipment count]" in slide.body_blocks[0]
    assert slide.placeholder_items == ["[please fill: shipment count]"]


def test_slide_spec_accepts_commercial_layout() -> None:
    slide = SlideSpec(
        index=1,
        role="content",
        layout="matrix_2x2",
        title="SWOT analysis",
        body_blocks=["S: source-grounded strength"],
    )

    assert slide.layout == "matrix_2x2"


def test_slide_spec_accepts_bluegreen_template_layouts() -> None:
    hub_slide = SlideSpec(
        index=1,
        role="content",
        layout="hub_spoke",
        title="Business ecosystem",
        body_blocks=["Center: One-card platform", "Dining", "Hotel", "Gym", "Retail"],
    )
    roles_slide = SlideSpec(
        index=2,
        role="content",
        layout="party_roles",
        title="Partner responsibilities",
        body_blocks=["Party A: site operations", "Party B: brand activation"],
    )

    assert hub_slide.layout == "hub_spoke"
    assert roles_slide.layout == "party_roles"


def test_slide_plan_rejects_duplicate_slide_indexes() -> None:
    with pytest.raises(ValidationError):
        SlidePlan(
            brief=PptRequestBrief(topic="Demo", purpose="demo"),
            scene="simple_formal",
            style="simple_formal",
            slides=[
                SlideSpec(index=1, role="cover", title="Cover"),
                SlideSpec(index=1, role="summary", title="Summary"),
            ],
        )
