# PPT Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an internal PPT Agent MVP that turns user text plus supported attachments into a real editable `.pptx` using template-first planning, PptxGenJS rendering, and lightweight validation.

**Architecture:** The SDK owns reusable PPT schemas, template routing, asset sourcing, rendering tool wrappers, and validation. A Node-based `ya-pptx-renderer` package uses PptxGenJS to render structured slide specs into `.pptx`; YA Claw exposes the product through a `ppt-agent` profile, while yaacli remains the fast manual validation path.

**Tech Stack:** Python 3.11+, Pydantic, ya-agent-sdk toolsets, YA Claw profiles, Node ESM, PptxGenJS, Vitest, pytest, pnpm, uv.

______________________________________________________________________

## MVP Decisions

- Default output is a real `.pptx` file only.
- User-facing brief confirmation is skipped; brief and slide plan are internal state.
- Missing business data, numbers, real names, and factual claims are kept as editable placeholders.
- Text, titles, body content, tables, placeholders, and major shapes must be native editable PPT objects.
- Complex decorations, stock backgrounds, generated illustrations, and user images may be inserted as image objects.
- No video support in MVP.
- Internet image sourcing is enabled by default when API keys are configured; no online PPT templates are downloaded.
- Asset source metadata is stored in an internal manifest for traceability.
- Templates are scene-first and skin-second. MVP scenes are `teaching_lesson`, `work_report`, `business_proposal`, and fallback `simple_formal`.
- Rendering uses PptxGenJS. Python wraps it as an SDK tool and validates the resulting PPTX.
- MVP validation is deterministic: parseable file, expected slide count, hard text present, placeholders preserved, attachment usage recorded.

## File Structure

### Python SDK

- Create `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/__init__.py`
  - Exposes PPT tools in the SDK core tool registry.
- Create `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/schemas.py`
  - Pydantic models for request brief, slide specs, template profiles, asset manifest, render manifest, and validation results.
- Create `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/templates.py`
  - Loads structured template assets from JSON.
- Create `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/router.py`
  - Rule-based template candidate selection.
- Create `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/assets.py`
  - Pexels/Unsplash image search and fallback asset records.
- Create `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/renderer.py`
  - Python wrapper that writes render input JSON, invokes the Node renderer, and reads manifest JSON.
- Create `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/validator.py`
  - Lightweight `.pptx` validation using `python-pptx`.
- Create `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/tool.py`
  - Agent-facing `pptx_render` tool.
- Create `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/data/templates/*.json`
  - MVP template profiles and layouts.
- Modify `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/__init__.py`
  - Mentions PPTX tools.
- Modify `packages/ya-agent-sdk/pyproject.toml`
  - Adds `python-pptx>=1.0.2` to the `document` and `all` extras, and the dev group.
- Modify `packages/ya-agent-sdk/.env.example`
  - Adds `YA_AGENT_PEXELS_API_KEY` and `YA_AGENT_UNSPLASH_ACCESS_KEY`.
- Modify `packages/ya-agent-sdk/ya_agent_sdk/_config.py`
  - Adds optional settings for image providers.

### Node Renderer

- Create `packages/ya-pptx-renderer/package.json`
  - Node package with `pptxgenjs`, `tsx`, and `vitest`.
- Create `packages/ya-pptx-renderer/src/render.mjs`
  - CLI entrypoint: reads render input JSON and writes `.pptx` plus render manifest JSON.
- Create `packages/ya-pptx-renderer/src/layouts.mjs`
  - Layout rendering functions for MVP slide roles.
- Create `packages/ya-pptx-renderer/src/theme.mjs`
  - Theme normalization and default styles.
- Create `packages/ya-pptx-renderer/test/render.test.mjs`
  - Vitest coverage for rendering a minimal deck.
- Modify `pnpm-workspace.yaml`
  - Adds `packages/ya-pptx-renderer`.

### YA Claw

- Modify `packages/ya-claw/profiles.yaml`
  - Adds a `ppt-agent` profile with `filesystem`, `shell`, `document`, `web`, and `pptx` toolsets.
- Modify `packages/ya-claw/ya_claw/execution/runtime.py`
  - Adds `pptx` to `_BUILTIN_TOOL_REGISTRY`.
- Modify `packages/ya-claw/tests/test_profile_resolver.py`
  - Verifies `ppt-agent` seed config can resolve.
- Modify `packages/ya-claw/.env.example`
  - Adds asset API key examples for Claw deployments.

### yaacli and Examples

- Modify `packages/yaacli/.env.example`
  - Adds asset API key examples.
- Create `examples/ppt_agent_mvp.py`
  - Runs the SDK tool directly against sample slide specs for local smoke validation.
- Modify `examples/.env.example`
  - Adds asset API key examples.

### Documentation

- Create `packages/ya-agent-sdk/README.md` section or add a small `packages/ya-agent-sdk/docs/pptx.md`
  - Documents how to call `pptx_render`, configure asset keys, and inspect manifest output.

______________________________________________________________________

## Data Contracts

Use these names consistently across Python schemas, renderer input JSON, and tests.

```python
class PptRequestBrief(BaseModel):
    topic: str
    audience: str | None = None
    purpose: str
    tone: str = "professional"
    expected_slide_count: int | None = None
    hard_requirements: list[str] = Field(default_factory=list)
    missing_placeholders: list[str] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)

class SlideVisualSlot(BaseModel):
    name: str
    kind: Literal["image", "background", "icon", "video_placeholder", "shape"]
    prompt: str | None = None
    source_path: str | None = None
    placeholder_text: str | None = None

class SlideSpec(BaseModel):
    index: int
    role: Literal["cover", "agenda", "section", "content", "case", "image_placeholder", "summary"]
    title: str
    subtitle: str | None = None
    body_blocks: list[str] = Field(default_factory=list)
    visual_slots: list[SlideVisualSlot] = Field(default_factory=list)
    speaker_notes: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    must_keep_text: list[str] = Field(default_factory=list)
    placeholder_items: list[str] = Field(default_factory=list)

class SlidePlan(BaseModel):
    brief: PptRequestBrief
    scene: Literal["teaching_lesson", "work_report", "business_proposal", "simple_formal"]
    style: Literal["campus_clean", "modern_business", "consulting_report", "simple_formal"]
    slides: list[SlideSpec]
```

______________________________________________________________________

## Task 1: Add Python PPTX Schemas

**Files:**

- Create: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/__init__.py`

- Create: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/schemas.py`

- Test: `packages/ya-agent-sdk/tests/toolsets/core/pptx/test_schemas.py`

- [ ] **Step 1: Write schema tests**

Create `packages/ya-agent-sdk/tests/toolsets/core/pptx/test_schemas.py` with tests that validate:

```python
from ya_agent_sdk.toolsets.core.pptx.schemas import PptRequestBrief, SlidePlan, SlideSpec


def test_slide_plan_accepts_mvp_roles() -> None:
    plan = SlidePlan(
        brief=PptRequestBrief(topic="Hot search fact checking", purpose="class lesson", expected_slide_count=2),
        scene="teaching_lesson",
        style="campus_clean",
        slides=[
            SlideSpec(index=1, role="cover", title="Hot Search"),
            SlideSpec(index=2, role="summary", title="Summary", body_blocks=["Check source first"]),
        ],
    )

    assert plan.slides[0].role == "cover"
    assert plan.brief.expected_slide_count == 2


def test_slide_spec_preserves_missing_data_placeholders() -> None:
    slide = SlideSpec(
        index=1,
        role="content",
        title="2025 Core Performance",
        body_blocks=["Completed [please fill: shipment count] nominated cargo cases"],
        placeholder_items=["[please fill: shipment count]"],
    )

    assert "[please fill: shipment count]" in slide.body_blocks[0]
    assert slide.placeholder_items == ["[please fill: shipment count]"]
```

- [ ] **Step 2: Run schema tests and confirm failure**

Run:

```bash
uv run python -m pytest packages/ya-agent-sdk/tests/toolsets/core/pptx/test_schemas.py -vv
```

Expected: import failure because `ya_agent_sdk.toolsets.core.pptx.schemas` does not exist.

- [ ] **Step 3: Implement schemas**

Create `schemas.py` with Pydantic models:

- `PptRequestBrief`
- `SlideVisualSlot`
- `SlideSpec`
- `SlidePlan`
- `TemplateLayout`
- `TemplateProfile`
- `AssetRecord`
- `AssetManifest`
- `RenderManifest`
- `PptxValidationResult`

Use `Literal` values listed in the data contract. Add a validator on `SlidePlan` that rejects duplicate slide indexes.

- [ ] **Step 4: Export models**

Create `__init__.py` exporting the schemas and no tools yet:

```python
from ya_agent_sdk.toolsets.core.pptx.schemas import (
    AssetManifest,
    AssetRecord,
    PptRequestBrief,
    PptxValidationResult,
    RenderManifest,
    SlidePlan,
    SlideSpec,
    SlideVisualSlot,
    TemplateLayout,
    TemplateProfile,
)

tools = []

__all__ = [
    "AssetManifest",
    "AssetRecord",
    "PptRequestBrief",
    "PptxValidationResult",
    "RenderManifest",
    "SlidePlan",
    "SlideSpec",
    "SlideVisualSlot",
    "TemplateLayout",
    "TemplateProfile",
    "tools",
]
```

- [ ] **Step 5: Verify**

Run:

```bash
uv run python -m pytest packages/ya-agent-sdk/tests/toolsets/core/pptx/test_schemas.py -vv
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx packages/ya-agent-sdk/tests/toolsets/core/pptx/test_schemas.py
git commit -m "feat(sdk): add pptx slide plan schemas"
```

______________________________________________________________________

## Task 2: Add Template Profiles and Rule Router

**Files:**

- Create: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/templates.py`

- Create: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/router.py`

- Create: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/data/templates/teaching_lesson.json`

- Create: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/data/templates/work_report.json`

- Create: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/data/templates/business_proposal.json`

- Create: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/data/templates/simple_formal.json`

- Test: `packages/ya-agent-sdk/tests/toolsets/core/pptx/test_router.py`

- [ ] **Step 1: Write router tests**

Create tests that assert:

```python
from ya_agent_sdk.toolsets.core.pptx.router import route_template


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


def test_falls_back_to_simple_formal() -> None:
    result = route_template("请帮我做一个PPT")
    assert result.scene_candidates[0] == "simple_formal"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
uv run python -m pytest packages/ya-agent-sdk/tests/toolsets/core/pptx/test_router.py -vv
```

Expected: import failure because `router.py` does not exist.

- [ ] **Step 3: Implement template JSON files**

Each template JSON must include:

- `id`
- `scene`
- `style`
- `keywords`
- `layouts`
- `theme`
- `asset_policy`

Use these layout ids in every scene:

- `cover`

- `agenda`

- `section`

- `content`

- `case`

- `image_placeholder`

- `summary`

- [ ] **Step 4: Implement `templates.py`**

Implement:

- `list_template_profiles() -> list[TemplateProfile]`
- `get_template_profile(scene: str, style: str | None = None) -> TemplateProfile`

Load JSON via `importlib.resources.files("ya_agent_sdk.toolsets.core.pptx") / "data" / "templates"`.

- [ ] **Step 5: Implement `router.py`**

Implement a deterministic keyword scorer:

- teaching keywords: `学生`, `课堂`, `班级`, `任务`, `思考`, `课件`, `目录`
- work report keywords: `述职`, `业绩`, `目标`, `团队协作`, `反思`, `入职`, `核心指标`
- business proposal keywords: `商业`, `承包`, `业态`, `餐饮`, `咖啡`, `酒店`, `健身`, `办公`, `规划`

Return a Pydantic model named `TemplateRouteResult` with:

- `scene_candidates: list[str]`

- `style_candidates: list[str]`

- `confidence: float`

- `matched_keywords: list[str]`

- [ ] **Step 6: Verify**

Run:

```bash
uv run python -m pytest packages/ya-agent-sdk/tests/toolsets/core/pptx/test_router.py -vv
```

Expected: all router tests pass.

- [ ] **Step 7: Commit**

```bash
git add packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx packages/ya-agent-sdk/tests/toolsets/core/pptx/test_router.py
git commit -m "feat(sdk): add ppt agent template router"
```

______________________________________________________________________

## Task 3: Add Node PptxGenJS Renderer Package

**Files:**

- Modify: `pnpm-workspace.yaml`

- Create: `packages/ya-pptx-renderer/package.json`

- Create: `packages/ya-pptx-renderer/src/render.mjs`

- Create: `packages/ya-pptx-renderer/src/layouts.mjs`

- Create: `packages/ya-pptx-renderer/src/theme.mjs`

- Test: `packages/ya-pptx-renderer/test/render.test.mjs`

- [ ] **Step 1: Add renderer package to pnpm workspace**

Modify `pnpm-workspace.yaml`:

```yaml
packages:
  - apps/*
  - packages/ya-pptx-renderer

onlyBuiltDependencies:
  - esbuild
```

- [ ] **Step 2: Add package manifest**

Create `packages/ya-pptx-renderer/package.json`:

```json
{
  "name": "ya-pptx-renderer",
  "private": true,
  "type": "module",
  "version": "0.0.0",
  "scripts": {
    "render": "node src/render.mjs",
    "test": "vitest run"
  },
  "dependencies": {
    "pptxgenjs": "^4.0.1",
    "zod": "^4.3.6"
  },
  "devDependencies": {
    "vitest": "^4.1.5"
  }
}
```

- [ ] **Step 3: Write renderer test**

Create `test/render.test.mjs` that:

- writes a minimal render input JSON to a temp directory,

- invokes `node src/render.mjs --input input.json --output out.pptx --manifest manifest.json`,

- asserts `out.pptx` and `manifest.json` exist.

- [ ] **Step 4: Run renderer test and confirm failure**

Run:

```bash
corepack pnpm install
corepack pnpm --dir packages/ya-pptx-renderer test
```

Expected: failure because `src/render.mjs` does not exist.

- [ ] **Step 5: Implement renderer**

Implement `render.mjs` CLI arguments:

- `--input`
- `--output`
- `--manifest`

Read JSON shape:

```json
{
  "plan": {
    "scene": "simple_formal",
    "style": "simple_formal",
    "brief": {"topic": "Demo", "purpose": "demo"},
    "slides": [{"index": 1, "role": "cover", "title": "Demo"}]
  },
  "template": {"id": "simple_formal", "theme": {}, "layouts": []},
  "assets": []
}
```

Use PptxGenJS to create one slide per spec. Add native text boxes for title and body blocks. Add image rectangles as native placeholders when no image path is available.

- [ ] **Step 6: Implement layout functions**

In `layouts.mjs`, export:

- `renderCoverSlide(pptx, slide, spec, theme, assets)`
- `renderAgendaSlide(pptx, slide, spec, theme, assets)`
- `renderContentSlide(pptx, slide, spec, theme, assets)`
- `renderImagePlaceholderSlide(pptx, slide, spec, theme, assets)`
- `renderSummarySlide(pptx, slide, spec, theme, assets)`
- `renderGenericSlide(pptx, slide, spec, theme, assets)`

Use editable text objects and editable shapes. Do not render a whole slide as one bitmap.

- [ ] **Step 7: Verify**

Run:

```bash
corepack pnpm --dir packages/ya-pptx-renderer test
```

Expected: renderer test passes.

- [ ] **Step 8: Commit**

```bash
git add pnpm-workspace.yaml packages/ya-pptx-renderer
git commit -m "feat(renderer): add pptxgenjs deck renderer"
```

______________________________________________________________________

## Task 4: Add Python Renderer Wrapper and PPTX Validator

**Files:**

- Modify: `packages/ya-agent-sdk/pyproject.toml`

- Create: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/renderer.py`

- Create: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/validator.py`

- Test: `packages/ya-agent-sdk/tests/toolsets/core/pptx/test_renderer.py`

- Test: `packages/ya-agent-sdk/tests/toolsets/core/pptx/test_validator.py`

- [ ] **Step 1: Add Python dependency**

Add `python-pptx>=1.0.2` to:

- `[project.optional-dependencies].document`

- `[project.optional-dependencies].all` through `document`

- `[dependency-groups].dev`

- [ ] **Step 2: Write wrapper test**

Create a test that builds a `SlidePlan`, calls:

```python
result = await render_pptx_with_node(
    plan=plan,
    template=template,
    assets=[],
    output_path=tmp_path / "deck.pptx",
    work_dir=tmp_path,
)
```

Assert:

- `result.output_path.endswith("deck.pptx")`

- output file exists

- `result.slide_count == len(plan.slides)`

- [ ] **Step 3: Write validator test**

Create a test that validates the renderer output:

```python
validation = validate_pptx(
    pptx_path=tmp_path / "deck.pptx",
    plan=plan,
)
assert validation.success is True
assert validation.slide_count == 1
```

- [ ] **Step 4: Run tests and confirm failure**

Run:

```bash
uv run python -m pytest packages/ya-agent-sdk/tests/toolsets/core/pptx/test_renderer.py packages/ya-agent-sdk/tests/toolsets/core/pptx/test_validator.py -vv
```

Expected: import failures because wrapper and validator do not exist.

- [ ] **Step 5: Implement renderer wrapper**

Implement `render_pptx_with_node`:

- serializes `plan`, `template`, and `assets` to `render-input.json`,
- resolves renderer script at repository root path `packages/ya-pptx-renderer/src/render.mjs`,
- calls `node` with `anyio.to_thread.run_sync` and `subprocess.run`,
- returns a `RenderManifest`.

Raise a clear `RuntimeError` when:

- `node` is missing,

- the renderer exits non-zero,

- output `.pptx` is missing,

- manifest JSON is missing.

- [ ] **Step 6: Implement validator**

Use `python-pptx` to:

- open the file,

- compare slide count,

- collect text from all shapes,

- verify every `must_keep_text` and `placeholder_items` value appears somewhere in the deck,

- return `PptxValidationResult(success=True, warnings=[...])` when parseable with non-critical warnings.

- [ ] **Step 7: Verify**

Run:

```bash
uv run python -m pytest packages/ya-agent-sdk/tests/toolsets/core/pptx/test_renderer.py packages/ya-agent-sdk/tests/toolsets/core/pptx/test_validator.py -vv
```

Expected: all tests pass when Node dependencies are installed.

- [ ] **Step 8: Commit**

```bash
git add packages/ya-agent-sdk/pyproject.toml packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx packages/ya-agent-sdk/tests/toolsets/core/pptx
git commit -m "feat(sdk): wrap pptx renderer and validator"
```

______________________________________________________________________

## Task 5: Add Internet Asset Sourcing

**Files:**

- Modify: `packages/ya-agent-sdk/ya_agent_sdk/_config.py`

- Create: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/assets.py`

- Test: `packages/ya-agent-sdk/tests/toolsets/core/pptx/test_assets.py`

- Modify: `packages/ya-agent-sdk/.env.example`

- Modify: `packages/yaacli/.env.example`

- Modify: `packages/ya-claw/.env.example`

- Modify: `examples/.env.example`

- [ ] **Step 1: Add settings**

Add fields to `AgentSettings`:

```python
pptx_pexels_api_key: str | None = None
pptx_unsplash_access_key: str | None = None
pptx_asset_search_enabled: bool = True
```

Environment names become:

- `YA_AGENT_PPTX_PEXELS_API_KEY`

- `YA_AGENT_PPTX_UNSPLASH_ACCESS_KEY`

- `YA_AGENT_PPTX_ASSET_SEARCH_ENABLED`

- [ ] **Step 2: Write tests with mocked HTTP**

Use `pytest_httpx` to verify:

- Pexels response maps to `AssetRecord(source="pexels", license="Pexels License")`.

- Unsplash response maps to `AssetRecord(source="unsplash", license="Unsplash License")`.

- Missing keys returns an empty list and does not raise.

- [ ] **Step 3: Implement `assets.py`**

Implement:

- `search_public_images(query: str, *, limit: int = 3) -> list[AssetRecord]`
- `_search_pexels(...)`
- `_search_unsplash(...)`

Use `httpx.AsyncClient`. Do not download images in this task; only return source metadata and candidate URLs.

- [ ] **Step 4: Update env examples**

Add comments:

```bash
# Optional public image search for PPT Agent backgrounds and illustrations.
YA_AGENT_PPTX_PEXELS_API_KEY=
YA_AGENT_PPTX_UNSPLASH_ACCESS_KEY=
YA_AGENT_PPTX_ASSET_SEARCH_ENABLED=true
```

- [ ] **Step 5: Verify**

Run:

```bash
uv run python -m pytest packages/ya-agent-sdk/tests/toolsets/core/pptx/test_assets.py -vv
```

Expected: tests pass without real API keys.

- [ ] **Step 6: Commit**

```bash
git add packages/ya-agent-sdk/ya_agent_sdk/_config.py packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/assets.py packages/ya-agent-sdk/tests/toolsets/core/pptx/test_assets.py packages/ya-agent-sdk/.env.example packages/yaacli/.env.example packages/ya-claw/.env.example examples/.env.example
git commit -m "feat(sdk): add pptx public image sourcing"
```

______________________________________________________________________

## Task 6: Add Agent-Facing `pptx_render` Tool

**Files:**

- Create: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/tool.py`

- Modify: `packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx/__init__.py`

- Test: `packages/ya-agent-sdk/tests/toolsets/core/pptx/test_tool.py`

- [ ] **Step 1: Write tool tests**

Test that:

- tool is unavailable when `file_operator` is missing,

- tool accepts a slide plan JSON string,

- tool writes output under the current workspace,

- tool returns `success`, `output_path`, `manifest_path`, `validation`.

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
uv run python -m pytest packages/ya-agent-sdk/tests/toolsets/core/pptx/test_tool.py -vv
```

Expected: import failure because `tool.py` does not exist.

- [ ] **Step 3: Implement `PptxRenderTool`**

Tool name: `pptx_render`

Arguments:

- `slide_plan_json: str`
- `output_file_name: str = "deck.pptx"`
- `template_scene: str | None = None`
- `template_style: str | None = None`

Behavior:

- parses `SlidePlan` from JSON,

- chooses template through explicit args or `plan.scene` / `plan.style`,

- creates a private tmp dir,

- calls Node renderer wrapper,

- validates output,

- writes `.pptx`, `render-manifest.json`, and `asset-manifest.json` through `file_operator`,

- returns relative workspace paths.

- [ ] **Step 4: Export tool**

Update `__init__.py`:

```python
from ya_agent_sdk.toolsets.core.pptx.tool import PptxRenderTool

tools = [PptxRenderTool]
__all__.append("PptxRenderTool")
```

- [ ] **Step 5: Verify**

Run:

```bash
uv run python -m pytest packages/ya-agent-sdk/tests/toolsets/core/pptx/test_tool.py -vv
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/ya-agent-sdk/ya_agent_sdk/toolsets/core/pptx packages/ya-agent-sdk/tests/toolsets/core/pptx/test_tool.py
git commit -m "feat(sdk): expose pptx render tool"
```

______________________________________________________________________

## Task 7: Register PPTX Toolset in YA Claw

**Files:**

- Modify: `packages/ya-claw/ya_claw/execution/runtime.py`

- Modify: `packages/ya-claw/profiles.yaml`

- Test: `packages/ya-claw/tests/test_runtime_builder.py`

- Test: `packages/ya-claw/tests/test_profile_resolver.py`

- [ ] **Step 1: Write runtime registry test**

Add an assertion that a profile with `builtin_toolsets=["pptx"]` resolves `PptxRenderTool` through `ClawRuntimeBuilder._resolve_builtin_tools`.

- [ ] **Step 2: Add registry entry**

In `runtime.py`, import:

```python
from ya_agent_sdk.toolsets.core.pptx import tools as pptx_tools
```

Add to `_BUILTIN_TOOL_REGISTRY`:

```python
"pptx": list(pptx_tools),
```

- [ ] **Step 3: Add `ppt-agent` seed profile**

Append to `packages/ya-claw/profiles.yaml`:

```yaml
- name: ppt-agent
  model: gateway@openai-responses:gpt-5.5
  model_settings_preset: openai_responses_high
  model_config_preset: gpt5_270k
  system_prompt: |-
    You are a PPT Agent for internal use. Generate a real editable .pptx file from user requirements and supported attachments.
    Do not invent business data, numeric metrics, customer names, legal facts, or real-world case details. Preserve missing facts as editable placeholders.
    Use template-first planning. Produce an internal SlidePlan JSON, call pptx_render, and return the final .pptx path.
    Use public image search for background and generic illustration assets when useful. Do not download online PPT templates.
  builtin_toolsets:
    - filesystem
    - shell
    - document
    - web
    - pptx
```

- [ ] **Step 4: Verify profile resolver**

Add a test assertion that a seed file containing `ppt-agent` resolves `builtin_toolsets == ["filesystem", "shell", "document", "web", "pptx"]`.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run python -m pytest packages/ya-claw/tests/test_profile_resolver.py packages/ya-claw/tests/test_runtime_builder.py -vv
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/ya-claw/ya_claw/execution/runtime.py packages/ya-claw/profiles.yaml packages/ya-claw/tests/test_profile_resolver.py packages/ya-claw/tests/test_runtime_builder.py
git commit -m "feat(claw): add ppt agent profile and toolset"
```

______________________________________________________________________

## Task 8: Add MVP Sample Cases and Direct Smoke Script

**Files:**

- Create: `examples/ppt_agent_mvp.py`

- Create: `examples/fixtures/ppt_agent/classroom_fact_checking.json`

- Create: `examples/fixtures/ppt_agent/work_report_placeholders.json`

- Create: `examples/fixtures/ppt_agent/park_business_proposal.json`

- Test: `packages/ya-agent-sdk/tests/toolsets/core/pptx/test_mvp_cases.py`

- [ ] **Step 1: Add fixture slide plans**

Create three JSON fixtures:

- classroom case: 12 slides, hard requirements include `热搜打假，沐光而行`, `八（6）班热搜榜`, and the three task titles.

- work report case: includes placeholders such as `[请补充：2025年货量/票数/收入/利润/客户数]`.

- park case: includes A/B/C/D business zones and roles.

- [ ] **Step 2: Write fixture validation tests**

Tests should load each fixture through `SlidePlan.model_validate_json` and assert:

- classroom plan has at least 10 slides,

- work report plan contains placeholder text,

- park plan mentions all A/B/C/D zones.

- [ ] **Step 3: Add smoke script**

`examples/ppt_agent_mvp.py` should:

- accept `--fixture` and `--output`,

- load a fixture,

- call `render_pptx_with_node`,

- call `validate_pptx`,

- print output path and validation warnings.

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m pytest packages/ya-agent-sdk/tests/toolsets/core/pptx/test_mvp_cases.py -vv
uv run python examples/ppt_agent_mvp.py --fixture examples/fixtures/ppt_agent/classroom_fact_checking.json --output /tmp/ppt-agent-classroom.pptx
```

Expected: tests pass and `/tmp/ppt-agent-classroom.pptx` exists.

- [ ] **Step 5: Commit**

```bash
git add examples/ppt_agent_mvp.py examples/fixtures/ppt_agent packages/ya-agent-sdk/tests/toolsets/core/pptx/test_mvp_cases.py
git commit -m "test: add ppt agent mvp sample cases"
```

______________________________________________________________________

## Task 9: Document yaacli and YA Claw Usage

**Files:**

- Create: `packages/ya-agent-sdk/docs/pptx.md`

- Modify: `packages/ya-claw/README.md`

- Modify: `packages/yaacli/README.md`

- [ ] **Step 1: Add SDK documentation**

Document:

- `pptx_render` input shape,

- how placeholders should be used,

- renderer dependency on Node and PptxGenJS,

- asset API key env vars,

- manifest files.

- [ ] **Step 2: Add YA Claw usage**

Document:

```bash
YA_CLAW_API_TOKEN=local-token uv run --package ya-claw ya-claw serve --reload
```

Then use profile `ppt-agent` from the web app or API.

- [ ] **Step 3: Add yaacli validation note**

Document that the developer can run yaacli with a prompt asking the agent to produce `SlidePlan` JSON and call `pptx_render` in the current workspace.

- [ ] **Step 4: Verify docs are referenced**

Run:

```bash
rg -n "ppt-agent|pptx_render|YA_AGENT_PPTX" packages/ya-agent-sdk/docs packages/ya-claw/README.md packages/yaacli/README.md
```

Expected: all terms appear.

- [ ] **Step 5: Commit**

```bash
git add packages/ya-agent-sdk/docs/pptx.md packages/ya-claw/README.md packages/yaacli/README.md
git commit -m "docs: document ppt agent mvp workflow"
```

______________________________________________________________________

## Task 10: Final Validation

**Files:**

- No new files unless previous tasks reveal a concrete defect.

- [ ] **Step 1: Install dependencies**

Run:

```bash
uv sync --all-packages
corepack pnpm install
```

Expected: lock files update only if new dependencies require it.

- [ ] **Step 2: Run focused tests**

Run:

```bash
uv run python -m pytest packages/ya-agent-sdk/tests/toolsets/core/pptx packages/ya-claw/tests/test_profile_resolver.py packages/ya-claw/tests/test_runtime_builder.py -vv
corepack pnpm --dir packages/ya-pptx-renderer test
```

Expected: all focused tests pass.

- [ ] **Step 3: Run repository checks**

Run:

```bash
make lint
make check
make test
```

Expected: all pass. If full `make test` is too slow during local iteration, record the focused tests and run the full suite before merge.

- [ ] **Step 4: Generate all three MVP decks**

Run:

```bash
uv run python examples/ppt_agent_mvp.py --fixture examples/fixtures/ppt_agent/classroom_fact_checking.json --output /tmp/ppt-agent-classroom.pptx
uv run python examples/ppt_agent_mvp.py --fixture examples/fixtures/ppt_agent/work_report_placeholders.json --output /tmp/ppt-agent-work-report.pptx
uv run python examples/ppt_agent_mvp.py --fixture examples/fixtures/ppt_agent/park_business_proposal.json --output /tmp/ppt-agent-park.pptx
```

Expected:

- three `.pptx` files exist,

- validation success is printed for each,

- placeholder text appears in the work report deck,

- classroom deck contains the required title and agenda terms,

- park deck contains A/B/C/D zone terms.

- [ ] **Step 5: Commit final fixes**

```bash
git status --short
git add pnpm-lock.yaml uv.lock .
git commit -m "feat: add ppt agent mvp"
```

Only commit lock files if dependency installation actually changed them.

______________________________________________________________________

## Not In MVP

- Full visual reflection with slide screenshots.
- Complex editing of existing `.pptx` object trees.
- Video insertion.
- Animation and master slide preservation.
- Large multi-document synthesis.
- Online PPT template crawling.
- Persistent saving of user-uploaded templates without explicit user action.
- Full ya-claw-web custom upload/download UX beyond existing session file paths.

## Self-Review

- Spec coverage: The plan covers direct `.pptx` generation, template-first routing, public image sourcing, no video, no fabricated data, editable native objects, internal manifests, Claw profile integration, and yaacli validation.
- Placeholder scan: The plan contains no implementation placeholders for MVP behavior; deferred items are explicitly listed as outside MVP scope.
- Type consistency: `PptRequestBrief`, `SlidePlan`, `SlideSpec`, `TemplateProfile`, `AssetRecord`, `AssetManifest`, `RenderManifest`, and `PptxValidationResult` are introduced before use and referenced consistently.
