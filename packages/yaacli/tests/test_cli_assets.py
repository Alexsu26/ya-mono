"""Tests for CLI bootstrap assets."""

from __future__ import annotations

import builtins

from yaacli.cli import _builtin_subagent_presets


def test_builtin_subagent_presets_do_not_import_subagents_runtime(monkeypatch) -> None:
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "ya_agent_sdk.subagents" or name.startswith("ya_agent_sdk.subagents."):
            raise AssertionError("setup must not import the subagents runtime package")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    preset_names = {item.name for item in _builtin_subagent_presets().iterdir()}

    assert "code-reviewer.md" in preset_names
    assert "debugger.md" in preset_names
