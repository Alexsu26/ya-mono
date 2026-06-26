from __future__ import annotations

from pathlib import Path

from ya_agent_sdk.toolsets.core.pptx.renderer import render_pptx_with_node
from ya_agent_sdk.toolsets.core.pptx.schemas import PptRequestBrief, SlidePlan, SlideSpec
from ya_agent_sdk.toolsets.core.pptx.templates import get_template_profile


async def test_render_pptx_with_node_writes_deck(tmp_path: Path) -> None:
    plan = SlidePlan(
        brief=PptRequestBrief(topic="Demo", purpose="demo"),
        scene="simple_formal",
        style="simple_formal",
        slides=[SlideSpec(index=1, role="cover", title="Demo")],
    )
    template = get_template_profile("simple_formal", "simple_formal")

    result = await render_pptx_with_node(
        plan=plan,
        template=template,
        assets=[],
        output_path=tmp_path / "deck.pptx",
        work_dir=tmp_path,
    )

    assert result.output_path.endswith("deck.pptx")
    assert (tmp_path / "deck.pptx").exists()
    assert result.slide_count == len(plan.slides)


async def test_render_pptx_with_node_attaches_bluegreen_template_assets(tmp_path: Path) -> None:
    plan = SlidePlan(
        brief=PptRequestBrief(topic="Business proposal", purpose="proposal"),
        scene="business_proposal",
        style="consulting_report",
        slides=[
            SlideSpec(index=1, role="cover", title="Business proposal"),
            SlideSpec(index=2, role="section", title="Project Context", subtitle="01"),
            SlideSpec(
                index=3,
                role="content",
                layout="hub_spoke",
                title="Ecosystem",
                body_blocks=[
                    "Central: one-card system",
                    "Food: meals",
                    "Hotel: stays",
                    "Gym: wellness",
                    "Retail: services",
                ],
            ),
            SlideSpec(
                index=4,
                role="content",
                layout="party_roles",
                title="Roles",
                body_blocks=["Owner: assets", "Operator: execution", "Tenant: services", "Designer: delivery"],
            ),
            SlideSpec(
                index=5,
                role="content",
                layout="timeline",
                title="Roadmap",
                body_blocks=["Phase 1: align", "Phase 2: design", "Phase 3: launch"],
            ),
            SlideSpec(
                index=6,
                role="content",
                layout="risk_grid",
                title="Risks",
                body_blocks=["Market: staged招商", "Cost: budget gate"],
            ),
            SlideSpec(
                index=7,
                role="content",
                layout="two_column",
                title="Operating Model",
                body_blocks=["Core: membership", "Evidence: source-grounded"],
            ),
            SlideSpec(index=8, role="summary", title="Next Steps", body_blocks=["Proceed with validation"]),
        ],
    )
    template = get_template_profile("business_proposal", "consulting_report")

    result = await render_pptx_with_node(
        plan=plan,
        template=template,
        assets=[],
        output_path=tmp_path / "business.pptx",
        work_dir=tmp_path,
    )

    assert result.slide_count == len(plan.slides)
    assert any(asset.kind == "template_background" for asset in result.assets)
    assert {asset.metadata.get("layout") for asset in result.assets} >= {"cover", "section", "hub_spoke"}
