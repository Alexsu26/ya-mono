"""Template profile loading for PPTX generation."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from ya_agent_sdk.toolsets.core.pptx.schemas import TemplateProfile


@lru_cache(maxsize=1)
def list_template_profiles() -> list[TemplateProfile]:
    template_dir = resources.files("ya_agent_sdk.toolsets.core.pptx") / "data" / "templates"
    profiles: list[TemplateProfile] = []
    for template_file in sorted(template_dir.iterdir(), key=lambda item: item.name):
        if template_file.name.endswith(".json"):
            profiles.append(TemplateProfile.model_validate(json.loads(template_file.read_text())))
    return profiles


def get_template_profile(scene: str, style: str | None = None) -> TemplateProfile:
    for profile in list_template_profiles():
        if profile.scene == scene and (style is None or profile.style == style):
            return profile
    raise ValueError(f"No PPTX template profile for scene={scene!r}, style={style!r}")
