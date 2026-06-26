#!/usr/bin/env node

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import pptxgen from "pptxgenjs";
import { z } from "zod";
import {
  renderAgendaSlide,
  renderContentSlide,
  renderCoverSlide,
  renderGenericSlide,
  renderHeroImageSlide,
  renderHubSpokeSlide,
  renderImagePlaceholderSlide,
  renderMatrixSlide,
  renderMetricCardsSlide,
  renderPartyRolesSlide,
  renderRiskGridSlide,
  renderSectionSlide,
  renderSummarySlide,
  renderTimelineSlide,
  renderTwoColumnSlide
} from "./layouts.mjs";
import { normalizeTheme } from "./theme.mjs";

const SlideSpec = z.object({
  index: z.number(),
  role: z.string(),
  layout: z.string().optional(),
  title: z.string(),
  subtitle: z.string().optional().nullable(),
  body_blocks: z.array(z.string()).optional(),
  visual_slots: z.array(z.record(z.string(), z.unknown())).optional()
});

const RenderInput = z.object({
  plan: z.object({
    scene: z.string(),
    style: z.string(),
    brief: z.record(z.string(), z.unknown()),
    slides: z.array(SlideSpec)
  }),
  template: z.record(z.string(), z.unknown()).optional(),
  assets: z.array(z.record(z.string(), z.unknown())).optional()
});

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    args[argv[i]] = argv[i + 1];
  }
  if (!args["--input"] || !args["--output"] || !args["--manifest"]) {
    throw new Error("Usage: render.mjs --input input.json --output out.pptx --manifest manifest.json");
  }
  return {
    input: args["--input"],
    output: args["--output"],
    manifest: args["--manifest"]
  };
}

function renderSlide(pptx, slide, spec, theme, assets) {
  if (spec.layout === "hero_image") return renderHeroImageSlide(pptx, slide, spec, theme, assets);
  if (spec.layout === "metric_cards") return renderMetricCardsSlide(pptx, slide, spec, theme, assets);
  if (spec.layout === "matrix_2x2") return renderMatrixSlide(pptx, slide, spec, theme, assets);
  if (spec.layout === "risk_grid") return renderRiskGridSlide(pptx, slide, spec, theme, assets);
  if (spec.layout === "timeline") return renderTimelineSlide(pptx, slide, spec, theme, assets);
  if (spec.layout === "two_column") return renderTwoColumnSlide(pptx, slide, spec, theme, assets);
  if (spec.layout === "hub_spoke") return renderHubSpokeSlide(pptx, slide, spec, theme, assets);
  if (spec.layout === "party_roles") return renderPartyRolesSlide(pptx, slide, spec, theme, assets);
  if (spec.role === "cover") return renderCoverSlide(pptx, slide, spec, theme, assets);
  if (spec.role === "agenda") return renderAgendaSlide(pptx, slide, spec, theme, assets);
  if (spec.role === "section") return renderSectionSlide(pptx, slide, spec, theme, assets);
  if (spec.role === "content" || spec.role === "case") {
    return renderContentSlide(pptx, slide, spec, theme, assets);
  }
  if (spec.role === "image_placeholder") {
    return renderImagePlaceholderSlide(pptx, slide, spec, theme, assets);
  }
  if (spec.role === "summary") return renderSummarySlide(pptx, slide, spec, theme, assets);
  return renderGenericSlide(pptx, slide, spec, theme, assets);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const rawInput = JSON.parse(await readFile(args.input, "utf8"));
  const input = RenderInput.parse(rawInput);
  const pptx = new pptxgen();
  pptx.layout = "LAYOUT_WIDE";
  pptx.author = "YA PPTX Renderer";
  pptx.subject = input.plan.brief?.topic ?? "Generated deck";
  pptx.title = input.plan.brief?.topic ?? "Generated deck";
  pptx.company = "YA";
  pptx.theme = {
    headFontFace: "Aptos",
    bodyFontFace: "Aptos",
    lang: "en-US"
  };

  const theme = normalizeTheme(input.template ?? {});
  const assets = input.assets ?? [];
  const slides = [...input.plan.slides].sort((a, b) => a.index - b.index);
  for (const spec of slides) {
    const slide = pptx.addSlide();
    renderSlide(pptx, slide, spec, theme, assets);
    if (spec.speaker_notes) {
      slide.addNotes(spec.speaker_notes);
    }
  }

  await mkdir(path.dirname(args.output), { recursive: true });
  await mkdir(path.dirname(args.manifest), { recursive: true });
  await pptx.writeFile({ fileName: args.output });
  await writeFile(
    args.manifest,
    JSON.stringify(
      {
        output_path: args.output,
        manifest_path: args.manifest,
        slide_count: slides.length,
        renderer: "ya-pptx-renderer",
        assets,
        warnings: [],
        metadata: {
          scene: input.plan.scene,
          style: input.plan.style
        }
      },
      null,
      2
    )
  );
}

main().catch((error) => {
  console.error(error?.stack ?? error);
  process.exit(1);
});
