from __future__ import annotations

from ya_agent_sdk.toolsets.core.pptx.router import route_template
from ya_agent_sdk.toolsets.core.pptx.templates import get_template_profile


def test_routes_classroom_request_to_teaching_lesson() -> None:
    result = route_template("八（6）班 热搜榜 学生 课堂 任务 思考")
    assert result.scene_candidates[0] == "teaching_lesson"
    assert "campus_clean" in result.style_candidates


def test_routes_report_request_to_work_report() -> None:
    result = route_template("述职报告 2025年核心业绩 团队协作 反思与前瞻")
    assert result.scene_candidates[0] == "work_report"


def test_routes_park_business_request_to_business_proposal() -> None:
    result = route_template("改造公园 商业承包 餐饮 咖啡厅 酒店 健身")
    assert result.scene_candidates[0] == "business_proposal"
    assert result.style_candidates[0] == "consulting_report"


def test_loads_bluegreen_business_consulting_profile() -> None:
    profile = get_template_profile("business_proposal", "consulting_report")

    assert profile.id == "business_proposal_bluegreen"
    assert profile.theme["accentColor"] == "036EB8"
    assert profile.theme["secondaryAccentColor"] == "34BF49"
    assert {layout.id for layout in profile.layouts} >= {"hub_spoke", "party_roles"}


def test_falls_back_to_simple_formal() -> None:
    result = route_template("请帮我做一个PPT")
    assert result.scene_candidates[0] == "simple_formal"
