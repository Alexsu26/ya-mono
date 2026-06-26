# PPTX Toolset

The PPTX toolset renders an internal `SlidePlan` JSON payload into a real editable `.pptx` file.

## Tool

`pptx_render` accepts:

- `slide_plan_json`: JSON matching `SlidePlan`.
- `output_file_name`: workspace-relative output path, default `deck.pptx`.
- `template_scene`: optional scene override.
- `template_style`: optional style override.

The renderer writes:

- the `.pptx` deck,
- `render-manifest.json`,
- `asset-manifest.json`.

Text, titles, body blocks, placeholders, and major shapes are native PowerPoint objects. Missing business facts should stay as editable placeholders such as `[please fill: customer count]`.

`pptx_render` rejects title-only business slides. Agenda, content, case, and summary slides must include at least one `body_blocks` item or one `visual_slots` item so an agent cannot report an empty shell as a successful deck.

Supported commercial report layouts:

- `hero_image` for cover and context pages with a strong visual area.
- `metric_cards` for KPI, economic, and financial indicators.
- `matrix_2x2` for SWOT and Ansoff-style analysis.
- `risk_grid` for risk, impact, likelihood, and mitigation pages.
- `timeline` for phased implementation plans.
- `two_column` for operating models, comparisons, and evidence splits.
- `hub_spoke` for central systems, business ecosystems, and capability maps.
- `party_roles` for cooperation responsibilities and multi-party workstreams.

For business proposal decks, the default `consulting_report` style uses the blue-green cooperation proposal system derived from a user-supplied Chinese project-cooperation template: white background, blue `#036EB8` structural blocks, green `#34BF49` accents, strong `PART` navigation, section dividers, tables, timelines, hub-spoke diagrams, and party-role cards.

The optional `editorial_park` style remains available for darker, image-led lifestyle and urban-renewal decks where the blue-green corporate proposal grammar is not desired.

## Renderer

Rendering is performed by the Node package `packages/ya-pptx-renderer`, which uses PptxGenJS. Install Node dependencies before rendering:

```bash
corepack pnpm install
```

For direct smoke testing:

```bash
uv run python examples/ppt_agent_mvp.py --fixture examples/fixtures/ppt_agent/classroom_fact_checking.json --output /tmp/ppt-agent-classroom.pptx
```

## Asset Keys

Public image search is optional. The MVP records source metadata and candidate URLs; it does not download online PPT templates.

```bash
YA_AGENT_PPTX_PEXELS_API_KEY=
YA_AGENT_PPTX_UNSPLASH_ACCESS_KEY=
YA_AGENT_PPTX_ASSET_SEARCH_ENABLED=true
```
