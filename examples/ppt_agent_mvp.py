from __future__ import annotations

import argparse
from pathlib import Path

import anyio
from ya_agent_sdk.toolsets.core.pptx.renderer import render_pptx_with_node
from ya_agent_sdk.toolsets.core.pptx.schemas import SlidePlan
from ya_agent_sdk.toolsets.core.pptx.templates import get_template_profile
from ya_agent_sdk.toolsets.core.pptx.validator import validate_pptx


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Render a PPT Agent MVP fixture.")
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    plan = SlidePlan.model_validate_json(args.fixture.read_text(encoding="utf-8"))
    template = get_template_profile(plan.scene, plan.style)
    work_dir = args.output.parent / f".{args.output.stem}-render"
    result = await render_pptx_with_node(
        plan=plan,
        template=template,
        assets=[],
        output_path=args.output,
        work_dir=work_dir,
    )
    validation = validate_pptx(pptx_path=args.output, plan=plan)
    print(f"output={result.output_path}")
    print(f"validation_success={validation.success}")
    if validation.warnings:
        print("warnings=" + "; ".join(validation.warnings))


if __name__ == "__main__":
    anyio.run(_main)
