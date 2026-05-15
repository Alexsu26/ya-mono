"""Lightweight discovery helpers for TUI inspection commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ya_agent_sdk.subagents.config import SubagentConfig, load_subagent_from_file
from ya_agent_sdk.toolsets.skills.config import SkillConfig, load_skills_from_dir
from ya_agent_sdk.toolsets.skills.toolset import SHARED_SKILLS_DIR_NAME, SKILLS_DIR_NAME

from yaacli.config import ConfigManager


@dataclass(frozen=True)
class DiscoveredSkill:
    config: SkillConfig
    source: str

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def description(self) -> str:
        return self.config.description

    @property
    def path(self) -> Path:
        return self.config.path


@dataclass(frozen=True)
class DiscoveredSubagent:
    config: SubagentConfig
    path: Path
    disabled: bool = False

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def description(self) -> str:
        return self.config.description


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _skill_source(path: Path, *, cwd: Path, config_dir: Path) -> str:
    project_config_dir = cwd / ConfigManager.PROJECT_CONFIG_DIR
    shared_dir = Path.home() / ".agents"
    if _is_relative_to(path, project_config_dir):
        return "project"
    if _is_relative_to(path, cwd):
        return "workspace"
    if _is_relative_to(path, shared_dir):
        return "shared"
    if _is_relative_to(path, config_dir):
        return "global"
    return "other"


def discover_skills(*, cwd: Path, config_dir: Path) -> list[DiscoveredSkill]:
    """Discover effective skills using the same priority shape as the runtime.

    Later roots override earlier roots for duplicate skill names, matching
    ``SkillToolset``'s scan order in ``create_tui_runtime``.
    """

    cwd = cwd.resolve()
    config_dir = config_dir.expanduser().resolve()
    roots = (
        config_dir,
        Path.home() / ".agents",
        cwd,
        cwd / ConfigManager.PROJECT_CONFIG_DIR,
    )
    discovered: dict[str, DiscoveredSkill] = {}

    for root in roots:
        for skills_dir in (root / SHARED_SKILLS_DIR_NAME, root / SKILLS_DIR_NAME):
            for skill in load_skills_from_dir(skills_dir).values():
                discovered[skill.name] = DiscoveredSkill(
                    config=skill,
                    source=_skill_source(skill.path, cwd=cwd, config_dir=config_dir),
                )

    return sorted(discovered.values(), key=lambda skill: skill.name.lower())


def _subagent_overrides(config: Any) -> tuple[set[str], dict[str, Any]]:
    subagents_config = getattr(config, "subagents", None)
    disabled = set(getattr(subagents_config, "disabled", []) or [])
    overrides = dict(getattr(subagents_config, "overrides", {}) or {})
    return disabled, overrides


def discover_subagents(*, config: Any, config_dir: Path) -> list[DiscoveredSubagent]:
    """Discover configured user subagents from ``~/.yaacli/subagents``."""

    disabled, overrides = _subagent_overrides(config)
    subagents_dir = config_dir.expanduser() / "subagents"
    if not subagents_dir.is_dir():
        return []

    discovered: list[DiscoveredSubagent] = []
    for file_path in sorted(subagents_dir.glob("*.md")):
        try:
            subagent = load_subagent_from_file(file_path)
        except (TypeError, ValueError):
            continue

        override = overrides.get(subagent.name)
        if override is not None:
            updates: dict[str, Any] = {}
            for field_name in ("model", "model_settings", "model_cfg"):
                value = getattr(override, field_name, None)
                if value is not None:
                    updates[field_name] = value
            if updates:
                subagent = subagent.model_copy(update=updates)

        discovered.append(
            DiscoveredSubagent(
                config=subagent,
                path=file_path,
                disabled=subagent.name in disabled,
            )
        )

    return sorted(discovered, key=lambda subagent: subagent.name.lower())
