"""Deterministic PPTX template routing."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ya_agent_sdk.toolsets.core.pptx.schemas import PptScene, PptStyle

_SCENE_KEYWORDS: dict[PptScene, list[str]] = {
    "teaching_lesson": ["学生", "课堂", "班级", "任务", "思考", "课件", "目录"],
    "work_report": ["述职", "业绩", "目标", "团队协作", "反思", "入职", "核心指标"],
    "business_proposal": ["商业", "承包", "业态", "餐饮", "咖啡", "酒店", "健身", "办公", "规划"],
    "simple_formal": [],
}

_SCENE_STYLES: dict[PptScene, PptStyle] = {
    "teaching_lesson": "campus_clean",
    "work_report": "modern_business",
    "business_proposal": "consulting_report",
    "simple_formal": "simple_formal",
}


class TemplateRouteResult(BaseModel):
    scene_candidates: list[PptScene]
    style_candidates: list[PptStyle]
    confidence: float
    matched_keywords: list[str] = Field(default_factory=list)


def route_template(text: str) -> TemplateRouteResult:
    scored: list[tuple[PptScene, int, list[str]]] = []
    for scene, keywords in _SCENE_KEYWORDS.items():
        if scene == "simple_formal":
            continue
        matched = [keyword for keyword in keywords if keyword in text]
        scored.append((scene, len(matched), matched))

    scored.sort(key=lambda item: item[1], reverse=True)
    best_scene, best_score, matched_keywords = scored[0]
    if best_score == 0:
        best_scene = "simple_formal"
        matched_keywords = []

    ordered_scenes: list[PptScene] = [best_scene]
    ordered_scenes.extend(scene for scene, score, _ in scored if scene != best_scene and score > 0)
    if "simple_formal" not in ordered_scenes:
        ordered_scenes.append("simple_formal")

    style_candidates: list[PptStyle] = []
    for scene in ordered_scenes:
        style = _SCENE_STYLES[scene]
        if style not in style_candidates:
            style_candidates.append(style)

    total_keywords = len(_SCENE_KEYWORDS[best_scene]) or 1
    confidence = min(1.0, best_score / total_keywords) if best_score else 0.2

    return TemplateRouteResult(
        scene_candidates=ordered_scenes,
        style_candidates=style_candidates,
        confidence=confidence,
        matched_keywords=matched_keywords,
    )
