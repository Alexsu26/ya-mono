from __future__ import annotations

from pathlib import Path

from ya_agent_sdk.toolsets.core.pptx.schemas import SlidePlan

FIXTURE_DIR = Path(__file__).resolve().parents[6] / "examples" / "fixtures" / "ppt_agent"


def _load_plan(name: str) -> SlidePlan:
    return SlidePlan.model_validate_json((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_classroom_fixture_has_required_slide_count() -> None:
    plan = _load_plan("classroom_fact_checking.json")
    assert len(plan.slides) >= 10
    assert "热搜打假，沐光而行" in plan.brief.hard_requirements


def test_work_report_fixture_contains_placeholder_text() -> None:
    plan = _load_plan("work_report_placeholders.json")
    text = "\n".join(block for slide in plan.slides for block in slide.body_blocks)
    assert "[请补充：2025年货量/票数/收入/利润/客户数]" in text


def test_park_fixture_mentions_all_zones() -> None:
    plan = _load_plan("park_business_proposal.json")
    titles = "\n".join(slide.title for slide in plan.slides)
    for zone in ("A区", "B区", "C区", "D区"):
        assert zone in titles
