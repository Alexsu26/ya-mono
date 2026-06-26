from __future__ import annotations

from pathlib import Path

from ya_agent_sdk.toolsets.core.pptx.renderer import render_pptx_with_node
from ya_agent_sdk.toolsets.core.pptx.schemas import PptRequestBrief, SlidePlan, SlideSpec
from ya_agent_sdk.toolsets.core.pptx.templates import get_template_profile
from ya_agent_sdk.toolsets.core.pptx.validator import validate_pptx


async def test_validate_pptx_accepts_renderer_output(tmp_path: Path) -> None:
    plan = SlidePlan(
        brief=PptRequestBrief(topic="Demo", purpose="demo"),
        scene="simple_formal",
        style="simple_formal",
        slides=[
            SlideSpec(
                index=1,
                role="cover",
                title="Demo",
                must_keep_text=["Demo"],
            )
        ],
    )
    template = get_template_profile("simple_formal", "simple_formal")

    await render_pptx_with_node(
        plan=plan,
        template=template,
        assets=[],
        output_path=tmp_path / "deck.pptx",
        work_dir=tmp_path,
    )
    validation = validate_pptx(
        pptx_path=tmp_path / "deck.pptx",
        plan=plan,
    )

    assert validation.success is True
    assert validation.slide_count == 1


async def test_validate_pptx_rejects_empty_business_content_pages(tmp_path: Path) -> None:
    plan = SlidePlan(
        brief=PptRequestBrief(topic="Business proposal", purpose="proposal"),
        scene="business_proposal",
        style="consulting_report",
        slides=[
            SlideSpec(index=1, role="cover", title="Business proposal"),
            SlideSpec(index=2, role="content", title="SWOT analysis"),
            SlideSpec(index=3, role="summary", title="Recommendation"),
        ],
    )
    template = get_template_profile("business_proposal", "consulting_report")

    await render_pptx_with_node(
        plan=plan,
        template=template,
        assets=[],
        output_path=tmp_path / "empty-business.pptx",
        work_dir=tmp_path,
    )
    validation = validate_pptx(
        pptx_path=tmp_path / "empty-business.pptx",
        plan=plan,
    )

    assert validation.success is False
    assert "Slide 2 'SWOT analysis' has no body blocks or visual slots" in validation.warnings
    assert "Slide 3 'Recommendation' has no body blocks or visual slots" in validation.warnings


async def test_validate_pptx_rejects_repetitive_consulting_report_without_template_rhythm(tmp_path: Path) -> None:
    plan = SlidePlan(
        brief=PptRequestBrief(topic="Business proposal", purpose="proposal"),
        scene="business_proposal",
        style="consulting_report",
        slides=[
            SlideSpec(index=1, role="cover", title="Business proposal"),
            SlideSpec(index=2, role="agenda", layout="two_column", title="Agenda", body_blocks=["A", "B"]),
            SlideSpec(index=3, role="content", layout="metric_cards", title="Metrics", body_blocks=["A: 1", "B: 2"]),
            SlideSpec(index=4, role="content", layout="metric_cards", title="Market", body_blocks=["A: 1", "B: 2"]),
            SlideSpec(
                index=5, role="case", layout="matrix_2x2", title="SWOT A", body_blocks=["S: A", "W: B", "O: C", "T: D"]
            ),
            SlideSpec(
                index=6, role="case", layout="matrix_2x2", title="SWOT B", body_blocks=["S: A", "W: B", "O: C", "T: D"]
            ),
            SlideSpec(index=7, role="content", layout="metric_cards", title="Financials", body_blocks=["A: 1", "B: 2"]),
            SlideSpec(index=8, role="content", layout="risk_grid", title="Risks", body_blocks=["Risk: mitigation"]),
            SlideSpec(index=9, role="summary", layout="two_column", title="Conclusion", body_blocks=["Proceed"]),
        ],
    )
    template = get_template_profile("business_proposal", "consulting_report")

    await render_pptx_with_node(
        plan=plan,
        template=template,
        assets=[],
        output_path=tmp_path / "repetitive-business.pptx",
        work_dir=tmp_path,
    )
    validation = validate_pptx(
        pptx_path=tmp_path / "repetitive-business.pptx",
        plan=plan,
    )

    assert validation.success is False
    assert "Business proposal consulting_report decks should include at least one section slide" in validation.warnings
    assert (
        "Business proposal consulting_report decks should include a hub_spoke ecosystem/system slide"
        in validation.warnings
    )
    assert (
        "Business proposal consulting_report decks should include a party_roles cooperation/workstream slide"
        in validation.warnings
    )
    assert any(
        "Business proposal consulting_report deck is too repetitive" in warning for warning in validation.warnings
    )
