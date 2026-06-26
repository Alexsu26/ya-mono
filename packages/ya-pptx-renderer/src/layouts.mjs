import pptxgen from "pptxgenjs";

const RECT = "rect";
const SLIDE_W = 13.333;
const SLIDE_H = 7.5;

function addBackground(slide, theme) {
  slide.background = { color: theme.backgroundColor };
}

function templateBackgrounds(theme) {
  return theme.assetPolicy?.template_backgrounds ?? {};
}

function backgroundKeyFor(spec) {
  if (spec.layout && spec.layout !== "default") return spec.layout;
  return spec.role;
}

function addTemplateBackground(slide, spec, theme, fallbackKey = null) {
  const backgrounds = templateBackgrounds(theme);
  const key = fallbackKey ?? backgroundKeyFor(spec);
  const backgroundPath = backgrounds[key] ?? backgrounds.content;
  if (!theme.assetPolicy?.template_backed || !backgroundPath) return false;
  slide.addImage({ path: backgroundPath, x: 0, y: 0, w: SLIDE_W, h: SLIDE_H });
  return true;
}

function addWhiteout(slide, { x, y, w, h, fill = "FFFFFF", transparency = 0 }) {
  slide.addShape(RECT, {
    x,
    y,
    w,
    h,
    fill: { color: fill, transparency },
    line: { transparency: 100 }
  });
}

function clearTemplateCanvas(slide, area = {}) {
  addWhiteout(slide, {
    x: area.x ?? 0,
    y: area.y ?? 0,
    w: area.w ?? SLIDE_W,
    h: area.h ?? SLIDE_H,
    fill: area.fill ?? "FFFFFF",
    transparency: area.transparency ?? 0
  });
}

function addConsultingHeader(slide, spec, theme) {
  slide.addShape(RECT, {
    x: 0,
    y: 0.0,
    w: SLIDE_W,
    h: 0.16,
    fill: { color: theme.accentColor },
    line: { color: theme.accentColor }
  });
  slide.addShape(RECT, {
    x: 0,
    y: 0.16,
    w: 2.0,
    h: 0.06,
    fill: { color: theme.secondaryAccentColor },
    line: { color: theme.secondaryAccentColor }
  });
  slide.addText(spec.section_label ?? "PART", {
    x: 0.45,
    y: 0.42,
    w: 0.72,
    h: 0.2,
    fontFace: theme.bodyFontFace ?? theme.fontFace,
    fontSize: 12,
    bold: true,
    color: "FFFFFF",
    fill: { color: theme.accentColor },
    align: "center",
    fit: "resize"
  });
  slide.addText(spec.chapter_title ?? spec.brief_section ?? "", {
    x: 1.28,
    y: 0.4,
    w: 3.0,
    h: 0.24,
    fontFace: theme.bodyFontFace ?? theme.fontFace,
    fontSize: 12,
    color: "666666",
    fit: "resize"
  });
}

function addTemplateStage(slide, spec, theme, fallbackKey = null) {
  if (!addTemplateBackground(slide, spec, theme, fallbackKey)) {
    addBackground(slide, theme);
    return false;
  }
  return true;
}

function shorten(text, maxChars = 58) {
  const value = String(text ?? "").replace(/\s+/g, " ").trim();
  if (value.length <= maxChars) return value;
  return `${value.slice(0, Math.max(0, maxChars - 1)).trim()}…`;
}

function bodyItems(spec, maxItems = 5, maxChars = 58) {
  return (spec.body_blocks ?? []).slice(0, maxItems).map((item) => shorten(item, maxChars));
}

function addTitle(slide, spec, theme, opts = {}) {
  slide.addText(spec.title ?? "", {
    x: opts.x ?? 0.65,
    y: opts.y ?? 0.45,
    w: opts.w ?? 8.9,
    h: opts.h ?? 0.7,
    fontFace: opts.fontFace ?? theme.titleFontFace ?? theme.fontFace,
    fontSize: opts.fontSize ?? 30,
    bold: true,
    color: theme.titleColor,
    fit: opts.fit ?? "resize"
  });
}

function addSubtitle(slide, spec, theme, y = 1.25) {
  if (!spec.subtitle) return;
  slide.addText(spec.subtitle, {
    x: 0.72,
    y,
    w: 8.4,
    h: 0.36,
    fontFace: theme.bodyFontFace ?? theme.fontFace,
    fontSize: 14,
    color: theme.bodyColor,
    fit: "resize"
  });
}

function addBodyBlocks(slide, spec, theme, opts = {}) {
  const blocks = bodyItems(spec, opts.maxItems ?? 5, opts.maxChars ?? 64);
  if (blocks.length === 0) return;
  const text = blocks.map((block) => `• ${block}`).join("\n");
  slide.addText(text, {
    x: opts.x ?? 0.85,
    y: opts.y ?? 1.55,
    w: opts.w ?? 8.4,
    h: opts.h ?? 3.6,
    fontFace: theme.bodyFontFace ?? theme.fontFace,
    fontSize: opts.fontSize ?? 17,
    color: theme.bodyColor,
    breakLine: false,
    valign: "top",
    fit: "resize"
  });
}

function parseLabelValue(text) {
  const raw = String(text ?? "");
  const delimiter = raw.match(/[:：]|\s-\s/);
  if (!delimiter) return { label: raw, value: "" };
  const index = delimiter.index ?? -1;
  if (index < 0) return { label: raw, value: "" };
  return {
    label: raw.slice(0, index).trim(),
    value: raw.slice(index + delimiter[0].length).trim()
  };
}

function addHeader(slide, spec, theme) {
  if (!theme.assetPolicy?.template_backed) {
    slide.addText(spec.section_label ?? "PART", {
      x: 0.08,
      y: 0.08,
      w: 1.05,
      h: 0.28,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 12,
      bold: true,
      color: theme.accentColor,
      fit: "resize"
    });
    slide.addText(spec.chapter_title ?? spec.brief_section ?? "", {
      x: 1.12,
      y: 0.08,
      w: 2.5,
      h: 0.28,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 12,
      color: theme.bodyColor,
      fit: "resize"
    });
  }
  addTitle(slide, spec, theme, { x: 0.5, y: 1.02, w: 5.0, h: 0.58, fontSize: 25 });
  if (spec.subtitle) {
    slide.addText(spec.subtitle, {
      x: 0.52,
      y: 1.58,
      w: 10.6,
      h: 0.28,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 14,
      color: theme.bodyColor,
      fit: "resize"
    });
  }
}

function addCard(slide, theme, { x, y, w, h, title, body, fill = theme.cardColor ?? "FFFFFF", accent = true }) {
  const onCardColor = fill === theme.cardColor ? theme.cardTextColor : theme.bodyColor;
  slide.addShape(RECT, {
    x,
    y,
    w,
    h,
    rectRadius: 0.08,
    fill: { color: fill },
    line: { color: accent ? theme.accentColor : "D9DEE7", transparency: accent ? 25 : 0 }
  });
  if (accent) {
    slide.addShape(RECT, {
      x,
      y,
      w: 0.08,
      h,
      fill: { color: theme.accentColor },
      line: { color: theme.accentColor }
    });
  }
  slide.addText(title ?? "", {
    x: x + 0.16,
    y: y + 0.12,
    w: w - 0.28,
    h: 0.28,
    fontFace: theme.titleFontFace ?? theme.fontFace,
    fontSize: 18,
    bold: true,
    color: fill === theme.cardColor ? theme.cardTextColor : theme.titleColor,
    fit: "resize"
  });
  slide.addText(shorten(body ?? "", 120), {
    x: x + 0.16,
    y: y + 0.48,
    w: w - 0.28,
    h: h - 0.58,
    fontFace: theme.bodyFontFace ?? theme.fontFace,
    fontSize: 16,
    color: onCardColor,
    fit: "resize",
    valign: "top"
  });
}

function editorialFill(theme, fallback = "FFFFFF") {
  return theme.cardColor ?? fallback;
}

function alternateEditorialFill(theme, fallback = "F8F3EA") {
  return theme.surfaceColor && theme.surfaceColor !== theme.backgroundColor ? theme.surfaceColor : fallback;
}

function addVisualPlaceholders(slide, spec, theme, opts = {}) {
  const slots = spec.visual_slots ?? [];
  slots.forEach((slot, index) => {
    const x = opts.x ?? 6.45;
    const y = (opts.y ?? 1.4) + index * 1.15;
    const w = opts.w ?? 2.55;
    const h = opts.h ?? 0.9;
    if (slot.source_path) {
      slide.addImage({ path: slot.source_path, x, y, w, h });
      return;
    }
    slide.addShape(RECT, {
      x,
      y,
      w,
      h,
      fill: { color: "F3F6F8" },
      line: { color: theme.accentColor, transparency: 35 }
    });
    slide.addText(slot.placeholder_text ?? slot.prompt ?? slot.name, {
      x: x + 0.1,
      y: y + 0.22,
      w: w - 0.2,
      h: h - 0.2,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 12,
      color: theme.bodyColor,
      align: "center",
      fit: "resize"
    });
  });
}

export function renderCoverSlide(pptx, slide, spec, theme, assets) {
  const templateBacked = addTemplateStage(slide, spec, theme, "cover");
  if (theme.templateId === "business_proposal_bluegreen") {
    if (templateBacked) {
      clearTemplateCanvas(slide);
      slide.addShape(RECT, {
        x: 0.75,
        y: 0.7,
        w: 0.12,
        h: 5.55,
        fill: { color: theme.accentColor },
        line: { color: theme.accentColor }
      });
      slide.addShape(RECT, {
        x: 8.75,
        y: 0.0,
        w: 4.58,
        h: SLIDE_H,
        fill: { color: theme.accentColor, transparency: 6 },
        line: { transparency: 100 }
      });
      addTitle(slide, spec, theme, { x: 1.25, y: 2.12, w: 6.6, h: 0.78, fontSize: 44 });
      if (spec.subtitle) {
        slide.addText(shorten(spec.subtitle, 72), {
          x: 1.3,
          y: 3.08,
          w: 6.4,
          h: 0.38,
          fontFace: theme.bodyFontFace ?? theme.fontFace,
          fontSize: 20,
          color: theme.bodyColor,
          fit: "resize",
          align: "left"
        });
      }
      return;
    }
    slide.addShape(RECT, {
      x: 2.64,
      y: 2.72,
      w: 7.65,
      h: 2.04,
      fill: { color: theme.accentColor },
      line: { color: theme.accentColor }
    });
    slide.addShape(RECT, {
      x: 3.28,
      y: 3.1,
      w: 6.58,
      h: 1.96,
      fill: { color: theme.secondaryAccentColor },
      line: { color: theme.secondaryAccentColor }
    });
    slide.addShape(RECT, {
      x: 0,
      y: 0.0,
      w: SLIDE_W,
      h: 0.18,
      fill: { color: theme.accentColor },
      line: { color: theme.accentColor }
    });
    slide.addText(spec.section_label ?? "PROPOSAL", {
      x: 5.32,
      y: 1.8,
      w: 3.8,
      h: 0.42,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 20,
      bold: true,
      charSpace: 4,
      color: theme.accentColor,
      align: "center",
      fit: "resize"
    });
    addTitle(slide, spec, theme, { x: 3.48, y: 3.54, w: 6.05, h: 0.72, fontSize: 30 });
    if (spec.subtitle) {
      slide.addText(spec.subtitle, {
        x: 6.2,
        y: 5.14,
        w: 3.85,
        h: 0.32,
        fontFace: theme.bodyFontFace ?? theme.fontFace,
        fontSize: 12,
        color: theme.bodyColor,
        fit: "resize",
        align: "right"
      });
    }
    return;
  }
  slide.addShape(RECT, {
    x: 0,
    y: 0,
    w: 10,
    h: 0.16,
    fill: { color: theme.accentColor },
    line: { color: theme.accentColor }
  });
  addTitle(slide, spec, theme, { x: 0.78, y: 1.8, w: 8.4, h: 0.9, fontSize: 36 });
  addSubtitle(slide, spec, theme, 2.76);
  addVisualPlaceholders(slide, spec, theme);
}

export function renderAgendaSlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "agenda")) {
    clearTemplateCanvas(slide);
  }
  addConsultingHeader(slide, spec, theme);
  addTitle(slide, spec, theme, { x: 0.82, y: 0.82, w: 4.1, h: 0.62, fontSize: 34 });
  const blocks = bodyItems(spec, 6, 54);
  blocks.forEach((block, index) => {
    const y = 1.72 + index * 0.74;
    slide.addShape(RECT, {
      x: 0.98,
      y,
      w: 0.46,
      h: 0.46,
      fill: { color: index % 2 === 0 ? theme.accentColor : theme.secondaryAccentColor },
      line: { transparency: 100 }
    });
    slide.addText(String(index + 1).padStart(2, "0"), {
      x: 0.98,
      y: y + 0.11,
      w: 0.46,
      h: 0.16,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 12,
      bold: true,
      color: "FFFFFF",
      align: "center"
    });
    slide.addText(block, {
      x: 1.7,
      y: y + 0.03,
      w: 9.0,
      h: 0.36,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 21,
      color: theme.bodyColor,
      fit: "resize"
    });
  });
}

export function renderContentSlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "content")) {
    clearTemplateCanvas(slide);
  }
  addConsultingHeader(slide, spec, theme);
  addTitle(slide, spec, theme, { fontSize: 32 });
  addSubtitle(slide, spec, theme, 1.12);
  addBodyBlocks(slide, spec, theme, { y: 1.72, w: 6.2, h: 3.9, fontSize: 18, maxItems: 5, maxChars: 62 });
  addVisualPlaceholders(slide, spec, theme);
}

export function renderImagePlaceholderSlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "content")) {
    clearTemplateCanvas(slide);
  }
  addConsultingHeader(slide, spec, theme);
  addTitle(slide, spec, theme, { fontSize: 32 });
  addVisualPlaceholders(slide, spec, theme, { x: 1.1, y: 1.45, w: 7.8, h: 3.45 });
  addBodyBlocks(slide, spec, theme, { y: 5.0, h: 0.6, fontSize: 16 });
}

export function renderSummarySlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "summary")) {
    clearTemplateCanvas(slide);
  }
  addConsultingHeader(slide, spec, theme);
  addTitle(slide, spec, theme, { fontSize: 34 });
  addBodyBlocks(slide, spec, theme, { y: 1.5, h: 3.9, fontSize: 20, maxItems: 5, maxChars: 60 });
}

export function renderSectionSlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "section")) {
    clearTemplateCanvas(slide);
    slide.addShape(RECT, {
      x: 0,
      y: 2.35,
      w: SLIDE_W,
      h: 1.62,
      fill: { color: theme.accentColor },
      line: { color: theme.accentColor }
    });
    slide.addShape("triangle", {
      x: 5.95,
      y: 3.85,
      w: 0.62,
      h: 0.58,
      rotate: 0,
      fill: { color: theme.secondaryAccentColor },
      line: { transparency: 100 }
    });
    const sectionNumber = spec.subtitle || String(spec.index).padStart(2, "0");
    slide.addText(sectionNumber, {
      x: 3.75,
      y: 2.74,
      w: 1.05,
      h: 0.54,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 34,
      bold: true,
      color: "FFFFFF",
      align: "right"
    });
    slide.addText(spec.title ?? "", {
      x: 5.05,
      y: 2.74,
      w: 4.75,
      h: 0.54,
      fontFace: theme.titleFontFace ?? theme.fontFace,
      fontSize: 32,
      bold: true,
      color: "FFFFFF",
      fit: "resize"
    });
    return;
  }
  addBackground(slide, theme);
  slide.addShape(RECT, {
    x: 0,
    y: 0,
    w: SLIDE_W,
    h: SLIDE_H,
    fill: { color: theme.backgroundColor },
    line: { transparency: 100 }
  });
  slide.addShape(RECT, {
    x: 0,
    y: 2.3,
    w: SLIDE_W,
    h: 2.92,
    fill: { color: theme.accentColor },
    line: { color: theme.accentColor }
  });
  const sectionNumber = spec.subtitle || String(spec.index).padStart(2, "0");
  slide.addText(sectionNumber, {
    x: 3.9,
    y: 3.12,
    w: 1.1,
    h: 0.8,
    fontFace: theme.bodyFontFace ?? theme.fontFace,
    fontSize: 38,
    bold: true,
    color: "FFFFFF",
    fit: "resize",
    align: "right"
  });
  slide.addText(spec.title ?? "", {
    x: 5.08,
    y: 3.14,
    w: 5.8,
    h: 0.76,
    fontFace: theme.titleFontFace ?? theme.fontFace,
    fontSize: 34,
    bold: true,
    color: "FFFFFF",
    fit: "resize"
  });
}

export function renderHeroImageSlide(pptx, slide, spec, theme, assets) {
  const backgroundKey = spec.role === "cover" ? "cover" : "content";
  const templateBacked = addTemplateStage(slide, spec, theme, backgroundKey);
  if (templateBacked) {
    clearTemplateCanvas(slide);
  } else {
    slide.addShape(RECT, {
      x: 0,
      y: 0,
      w: SLIDE_W,
      h: SLIDE_H,
      fill: { color: theme.backgroundColor },
      line: { transparency: 100 }
    });
  }
  const slot = (spec.visual_slots ?? []).find((item) => item.source_path);
  if (slot?.source_path) {
    slide.addImage({ path: slot.source_path, x: 7.15, y: 0, w: 6.18, h: SLIDE_H });
  } else {
    slide.addShape(RECT, {
      x: 7.15,
      y: 0,
      w: 6.18,
      h: SLIDE_H,
      fill: { color: "E7ECEF" },
      line: { transparency: 100 }
    });
  }
  if (templateBacked) {
    addConsultingHeader(slide, spec, theme);
  }
  slide.addShape(RECT, {
    x: 0.72,
    y: 0.72,
    w: 0.12,
    h: 4.9,
    fill: { color: theme.accentColor },
    line: { color: theme.accentColor }
  });
  addTitle(slide, spec, theme, { x: 1.05, y: 1.42, w: 5.7, h: 1.55, fontSize: 37 });
  addSubtitle(slide, spec, theme, 3.12);
  addBodyBlocks(slide, spec, theme, { x: 1.08, y: 3.72, w: 5.55, h: 1.75, fontSize: 17, maxItems: 4, maxChars: 56 });
}

export function renderMetricCardsSlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "metric_cards")) {
    clearTemplateCanvas(slide);
  }
  addConsultingHeader(slide, spec, theme);
  addHeader(slide, spec, theme);
  const blocks = bodyItems(spec, 6, 48);
  const columns = Math.min(Math.max(blocks.length, 1), 4);
  const cardW = (11.95 - (columns - 1) * 0.22) / columns;
  blocks.slice(0, 8).forEach((block, index) => {
    const parsed = parseLabelValue(block);
    const row = Math.floor(index / 4);
    const col = index % 4;
    addCard(slide, theme, {
      x: 0.7 + col * (cardW + 0.22),
      y: 1.55 + row * 2.05,
      w: cardW,
      h: 1.8,
      title: parsed.label,
      body: parsed.value || block,
      fill: row === 0 ? editorialFill(theme) : alternateEditorialFill(theme, "F6F7F8")
    });
  });
}

export function renderMatrixSlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "matrix_2x2")) {
    clearTemplateCanvas(slide);
  }
  addConsultingHeader(slide, spec, theme);
  addHeader(slide, spec, theme);
  const labels = ["Strengths", "Weaknesses", "Opportunities", "Threats"];
  const blocks = spec.body_blocks ?? [];
  const cells = labels.map((label, index) => {
    const parsed = parseLabelValue(blocks[index] ?? "");
    return { title: label, body: parsed.value || parsed.label || "Add evidence" };
  });
  const positions = [
    [0.75, 1.48],
    [6.9, 1.48],
    [0.75, 4.05],
    [6.9, 4.05]
  ];
  cells.forEach((cell, index) => {
    addCard(slide, theme, {
      x: positions[index][0],
      y: positions[index][1],
      w: 5.55,
      h: 2.18,
      title: cell.title,
      body: cell.body,
      fill: index % 2 === 0 ? editorialFill(theme) : alternateEditorialFill(theme)
    });
  });
  slide.addText("Market", {
    x: 6.08,
    y: 3.38,
    w: 1.1,
    h: 0.28,
    fontFace: theme.bodyFontFace ?? theme.fontFace,
    fontSize: 12,
    bold: true,
    color: theme.accentColor,
    align: "center"
  });
  slide.addText("Product", {
    x: 0.75,
    y: 3.38,
    w: 1.1,
    h: 0.28,
    fontFace: theme.bodyFontFace ?? theme.fontFace,
    fontSize: 12,
    bold: true,
    color: theme.accentColor,
    align: "center"
  });
}

export function renderRiskGridSlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "risk_grid")) {
    clearTemplateCanvas(slide);
  }
  addConsultingHeader(slide, spec, theme);
  addHeader(slide, spec, theme);
  const blocks = bodyItems(spec, 4, 86);
  const positions = [
    [0.82, 1.65],
    [6.92, 1.65],
    [0.82, 4.0],
    [6.92, 4.0]
  ];
  blocks.forEach((block, index) => {
    const parsed = parseLabelValue(block);
    const [x, y] = positions[index];
    const fill = index % 2 === 0 ? theme.accentColor : theme.secondaryAccentColor;
    slide.addShape(RECT, {
      x,
      y,
      w: 5.45,
      h: 1.72,
      fill: { color: "FFFFFF" },
      line: { color: fill, transparency: 12 }
    });
    slide.addShape(RECT, {
      x,
      y,
      w: 0.16,
      h: 1.72,
      fill: { color: fill },
      line: { color: fill }
    });
    slide.addText(shorten(parsed.label || block, 34), {
      x: x + 0.34,
      y: y + 0.18,
      w: 4.85,
      h: 0.36,
      fontFace: theme.titleFontFace ?? theme.fontFace,
      fontSize: 18,
      bold: true,
      color: theme.titleColor,
      fit: "resize"
    });
    slide.addText(shorten(parsed.value || "Define owner, trigger, and mitigation action.", 88), {
      x: x + 0.34,
      y: y + 0.72,
      w: 4.85,
      h: 0.62,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 16,
      color: theme.bodyColor,
      fit: "resize"
    });
  });
}

export function renderTimelineSlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "timeline")) {
    clearTemplateCanvas(slide);
  }
  addConsultingHeader(slide, spec, theme);
  addHeader(slide, spec, theme);
  const blocks = bodyItems(spec, 5, 56);
  const stepW = 11.7 / Math.max(blocks.length, 1);
  slide.addShape(RECT, {
    x: 0.85,
    y: 3.15,
    w: 11.55,
    h: 0.05,
    fill: { color: theme.accentColor },
    line: { color: theme.accentColor }
  });
  blocks.forEach((block, index) => {
    const parsed = parseLabelValue(block);
    const x = 0.85 + index * stepW;
    slide.addShape("ellipse", {
      x: x + 0.1,
      y: 2.88,
      w: 0.55,
      h: 0.55,
      fill: { color: theme.accentColor },
      line: { color: theme.accentColor }
    });
    slide.addText(String(index + 1), {
      x: x + 0.1,
      y: 3.01,
      w: 0.55,
      h: 0.16,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 14,
      bold: true,
      color: "FFFFFF",
      align: "center"
    });
    slide.addText(parsed.label || `Phase ${index + 1}`, {
      x,
      y: 1.75,
      w: stepW - 0.22,
      h: 0.42,
      fontFace: theme.titleFontFace ?? theme.fontFace,
      fontSize: 16,
      bold: true,
      color: theme.titleColor,
      fit: "resize"
    });
    slide.addText(shorten(parsed.value || block, 58), {
      x,
      y: 3.65,
      w: stepW - 0.22,
      h: 1.25,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 14,
      color: theme.bodyColor,
      fit: "resize",
      valign: "top"
    });
  });
}

export function renderTwoColumnSlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "two_column")) {
    clearTemplateCanvas(slide);
  }
  addConsultingHeader(slide, spec, theme);
  addHeader(slide, spec, theme);
  const blocks = bodyItems(spec, 6, 58);
  const visual = (spec.visual_slots ?? []).find((slot) => slot.source_path);
  if (visual?.source_path) {
    slide.addImage({ path: visual.source_path, x: 8.35, y: 0, w: 4.98, h: SLIDE_H });
    slide.addShape(RECT, {
      x: 8.35,
      y: 0,
      w: 0.08,
      h: SLIDE_H,
      fill: { color: theme.accentColor },
      line: { color: theme.accentColor }
    });
    const midpointWithImage = Math.ceil(blocks.length / 2);
    const columnsWithImage = [blocks.slice(0, midpointWithImage), blocks.slice(midpointWithImage)];
    columnsWithImage.forEach((items, index) => {
      addCard(slide, theme, {
        x: 0.75,
        y: index === 0 ? 1.45 : 4.05,
        w: 7.0,
        h: 2.12,
        title: index === 0 ? "Core proposition" : "Execution evidence",
        body: items.map((item) => `• ${item}`).join("\n"),
        fill: index === 0 ? editorialFill(theme) : alternateEditorialFill(theme)
      });
    });
    return;
  }
  const midpoint = Math.ceil(blocks.length / 2);
  const columns = [blocks.slice(0, midpoint), blocks.slice(midpoint)];
  columns.forEach((items, index) => {
    addCard(slide, theme, {
      x: index === 0 ? 0.75 : 6.85,
      y: 1.5,
      w: 5.6,
      h: 4.85,
      title: index === 0 ? "Core proposition" : "Execution evidence",
      body: items.map((item) => `• ${item}`).join("\n"),
      fill: index === 0 ? editorialFill(theme) : alternateEditorialFill(theme)
    });
  });
}

export function renderHubSpokeSlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "hub_spoke")) {
    clearTemplateCanvas(slide);
  }
  addConsultingHeader(slide, spec, theme);
  addHeader(slide, spec, theme);
  const blocks = bodyItems(spec, 7, 36);
  const parsedBlocks = blocks.map(parseLabelValue);
  const center = shorten(parsedBlocks[0]?.value || parsedBlocks[0]?.label || spec.title, 18);
  const nodes = parsedBlocks.slice(1, 7);
  const centerX = 4.85;
  const centerY = 3.0;
  const nodePositions = [
    [2.6, 1.8],
    [6.75, 1.8],
    [8.05, 3.45],
    [6.75, 5.1],
    [2.6, 5.1],
    [1.3, 3.45]
  ];
  slide.addShape("ellipse", {
    x: centerX,
    y: centerY,
    w: 2.1,
    h: 1.08,
    fill: { color: theme.secondaryAccentColor },
    line: { color: theme.secondaryAccentColor }
  });
  slide.addText(center, {
    x: centerX + 0.16,
    y: centerY + 0.24,
    w: 1.78,
    h: 0.48,
    fontFace: theme.titleFontFace ?? theme.fontFace,
    fontSize: 17,
    bold: true,
    color: "FFFFFF",
    fit: "resize",
    align: "center"
  });
  nodes.forEach((node, index) => {
    const [x, y] = nodePositions[index];
    slide.addShape(RECT, {
      x: x + 0.76,
      y: y + 0.45,
      w: centerX + 0.3 - x,
      h: 0.04,
      fill: { color: index % 2 === 0 ? theme.accentColor : theme.secondaryAccentColor, transparency: 15 },
      line: { transparency: 100 }
    });
    slide.addShape("ellipse", {
      x,
      y,
      w: 1.45,
      h: 0.9,
      fill: { color: index % 2 === 0 ? theme.accentColor : theme.secondaryAccentColor },
      line: { color: "FFFFFF", transparency: 15 }
    });
    slide.addText(shorten(node.value || node.label, 18), {
      x: x + 0.1,
      y: y + 0.18,
      w: 1.25,
      h: 0.42,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 14,
      bold: true,
      color: "FFFFFF",
      fit: "resize",
      align: "center"
    });
  });
}

export function renderPartyRolesSlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "party_roles")) {
    clearTemplateCanvas(slide);
  }
  addConsultingHeader(slide, spec, theme);
  addHeader(slide, spec, theme);
  const blocks = bodyItems(spec, 4, 74);
  const positions = [
    [0.95, 2.05],
    [6.85, 2.05],
    [0.95, 4.55],
    [6.85, 4.55]
  ];
  blocks.forEach((block, index) => {
    const parsed = parseLabelValue(block);
    const [x, y] = positions[index];
    const fill = index % 2 === 0 ? theme.accentColor : theme.secondaryAccentColor;
    slide.addShape(RECT, {
      x,
      y,
      w: 4.95,
      h: 1.36,
      fill: { color: "FFFFFF" },
      line: { color: fill, transparency: 15 }
    });
    slide.addShape(RECT, {
      x,
      y,
      w: 1.12,
      h: 1.36,
      fill: { color: fill },
      line: { color: fill }
    });
    slide.addText(String(index + 1).padStart(2, "0"), {
      x: x + 0.08,
      y: y + 0.38,
      w: 0.96,
      h: 0.36,
      fontFace: theme.titleFontFace ?? theme.fontFace,
      fontSize: 20,
      bold: true,
      color: "FFFFFF",
      align: "center"
    });
    slide.addText(parsed.label || `Party ${index + 1}`, {
      x: x + 1.3,
      y: y + 0.18,
      w: 3.4,
      h: 0.3,
      fontFace: theme.titleFontFace ?? theme.fontFace,
      fontSize: 18,
      bold: true,
      color: theme.titleColor,
      fit: "resize"
    });
    slide.addText(shorten(parsed.value || block, 72), {
      x: x + 1.3,
      y: y + 0.58,
      w: 3.38,
      h: 0.48,
      fontFace: theme.bodyFontFace ?? theme.fontFace,
      fontSize: 15,
      color: theme.bodyColor,
      fit: "resize"
    });
  });
}

export function renderGenericSlide(pptx, slide, spec, theme, assets) {
  if (addTemplateStage(slide, spec, theme, "content")) {
    clearTemplateCanvas(slide);
  }
  addConsultingHeader(slide, spec, theme);
  addTitle(slide, spec, theme, { fontSize: 32 });
  addSubtitle(slide, spec, theme, 1.08);
  addBodyBlocks(slide, spec, theme, { y: 1.48, h: 3.8 });
  addVisualPlaceholders(slide, spec, theme);
}
