"""Python wrapper around the Node PptxGenJS renderer."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import anyio.to_thread

from ya_agent_sdk.toolsets.core.pptx.schemas import AssetRecord, RenderManifest, SlidePlan, TemplateProfile


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _run_renderer(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, check=False, text=True)


def _template_asset_root(template_id: str) -> Path:
    return Path(__file__).parent / "data" / "template_assets" / template_id


def _prepare_template_payload(template: TemplateProfile, work_dir: Path) -> tuple[dict[str, Any], list[AssetRecord]]:
    template_payload = template.model_dump(mode="json")
    asset_root = _template_asset_root(template.id)
    manifest_path = asset_root / "manifest.json"
    if not manifest_path.exists():
        return template_payload, []

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backgrounds = manifest.get("backgrounds")
    if not isinstance(backgrounds, dict):
        return template_payload, []

    copied_dir = work_dir / "template-assets" / template.id
    copied_dir.mkdir(parents=True, exist_ok=True)
    prepared_backgrounds: dict[str, str] = {}
    template_assets: list[AssetRecord] = []
    for layout, relative_path in backgrounds.items():
        if not isinstance(layout, str) or not isinstance(relative_path, str):
            continue
        source_path = asset_root / relative_path
        if not source_path.exists():
            continue
        destination = copied_dir / source_path.name
        shutil.copyfile(source_path, destination)
        prepared_backgrounds[layout] = str(destination)
        template_assets.append(
            AssetRecord(
                id=f"{template.id}:{layout}",
                source="template",
                kind="template_background",
                title=f"{template.id} {layout} background",
                local_path=str(destination),
                metadata={"template_id": template.id, "layout": layout},
            )
        )

    if prepared_backgrounds:
        asset_policy = dict(template_payload.get("asset_policy") or {})
        asset_policy["template_backed"] = True
        asset_policy["template_backgrounds"] = prepared_backgrounds
        asset_policy["template_asset_manifest"] = manifest
        template_payload["asset_policy"] = asset_policy
    return template_payload, template_assets


async def render_pptx_with_node(
    *,
    plan: SlidePlan,
    template: TemplateProfile,
    assets: list[AssetRecord],
    output_path: Path,
    work_dir: Path,
) -> RenderManifest:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js executable was not found; install Node to render PPTX files")

    renderer_script = _repo_root() / "packages" / "ya-pptx-renderer" / "src" / "render.mjs"
    if not renderer_script.exists():
        raise RuntimeError(f"PPTX renderer script not found: {renderer_script}")

    work_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    input_path = work_dir / "render-input.json"
    manifest_path = work_dir / "render-manifest.json"
    template_payload, template_assets = _prepare_template_payload(template, work_dir)
    input_payload = {
        "plan": plan.model_dump(mode="json"),
        "template": template_payload,
        "assets": [asset.model_dump(mode="json") for asset in assets],
    }
    input_path.write_text(json.dumps(input_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    command = [
        node,
        str(renderer_script),
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--manifest",
        str(manifest_path),
    ]
    completed = await anyio.to_thread.run_sync(_run_renderer, command)
    if completed.returncode != 0:
        raise RuntimeError(
            f"PPTX renderer failed with exit code {completed.returncode}: {completed.stderr or completed.stdout}"
        )
    if not output_path.exists():
        raise RuntimeError(f"PPTX renderer did not create output file: {output_path}")
    if not manifest_path.exists():
        raise RuntimeError(f"PPTX renderer did not create manifest file: {manifest_path}")

    render_manifest = RenderManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if template_assets:
        render_manifest.assets.extend(template_assets)
    return render_manifest
