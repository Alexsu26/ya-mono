import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { describe, expect, it } from "vitest";

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.resolve(__dirname, "..");

describe("render CLI", () => {
  it("renders a minimal deck and manifest", async () => {
    const workDir = path.join(tmpdir(), `ya-pptx-renderer-${Date.now()}`);
    await mkdir(workDir, { recursive: true });
    const inputPath = path.join(workDir, "input.json");
    const outputPath = path.join(workDir, "out.pptx");
    const manifestPath = path.join(workDir, "manifest.json");

    await writeFile(
      inputPath,
      JSON.stringify({
        plan: {
          scene: "simple_formal",
          style: "simple_formal",
          brief: { topic: "Demo", purpose: "demo" },
          slides: [{ index: 1, role: "cover", title: "Demo" }]
        },
        template: { id: "simple_formal", theme: {}, layouts: [] },
        assets: []
      })
    );

    await execFileAsync("node", [
      path.join(packageRoot, "src", "render.mjs"),
      "--input",
      inputPath,
      "--output",
      outputPath,
      "--manifest",
      manifestPath
    ]);

    expect(existsSync(outputPath)).toBe(true);
    expect(existsSync(manifestPath)).toBe(true);
  });

  it("renders commercial report layouts as editable text shapes", async () => {
    const workDir = path.join(tmpdir(), `ya-pptx-renderer-commercial-${Date.now()}`);
    await mkdir(workDir, { recursive: true });
    const inputPath = path.join(workDir, "input.json");
    const outputPath = path.join(workDir, "out.pptx");
    const manifestPath = path.join(workDir, "manifest.json");

    await writeFile(
      inputPath,
      JSON.stringify({
        plan: {
          scene: "business_proposal",
          style: "consulting_report",
          brief: { topic: "Buffer Park", purpose: "proposal" },
          slides: [
            {
              index: 1,
              role: "content",
              layout: "metric_cards",
              title: "Core metrics",
              body_blocks: ["GDP: steady recovery", "Retail: resilient", "Tourism: strong"]
            },
            {
              index: 2,
              role: "content",
              layout: "matrix_2x2",
              title: "SWOT analysis",
              body_blocks: ["S: warehouse renewal", "W: ramp-up cost", "O: cultural tourism", "T: competition"]
            },
            {
              index: 3,
              role: "content",
              layout: "risk_grid",
              title: "Risk management",
              body_blocks: ["Market risk: medium impact", "Cost overrun: high impact", "Staffing: medium impact"]
            },
            {
              index: 4,
              role: "content",
              layout: "timeline",
              title: "Implementation roadmap",
              body_blocks: ["Month 1-2: design", "Month 3-5: fit-out", "Month 6: launch"]
            },
            {
              index: 5,
              role: "content",
              layout: "two_column",
              title: "Operating model",
              body_blocks: ["Left: one-card payment system", "Right: cross-promotion and events"]
            }
          ]
        },
        template: {
          id: "business_proposal",
          theme: {
            fontFace: "Aptos",
            titleColor: "172033",
            bodyColor: "2B3440",
            accentColor: "B7791F",
            backgroundColor: "FBFAF7"
          },
          layouts: []
        },
        assets: []
      })
    );

    await execFileAsync("node", [
      path.join(packageRoot, "src", "render.mjs"),
      "--input",
      inputPath,
      "--output",
      outputPath,
      "--manifest",
      manifestPath
    ]);

    const slideXml = await execFileAsync("unzip", ["-p", outputPath, "ppt/slides/slide2.xml"]);
    expect(slideXml.stdout).toContain("SWOT analysis");
    expect(slideXml.stdout).toContain("warehouse renewal");
    expect(slideXml.stdout).toContain("Market");
    expect(slideXml.stdout).toContain("Product");
  });

  it("renders editorial park theme with dark section rhythm and serif display type", async () => {
    const workDir = path.join(tmpdir(), `ya-pptx-renderer-editorial-${Date.now()}`);
    await mkdir(workDir, { recursive: true });
    const inputPath = path.join(workDir, "input.json");
    const outputPath = path.join(workDir, "out.pptx");
    const manifestPath = path.join(workDir, "manifest.json");

    await writeFile(
      inputPath,
      JSON.stringify({
        plan: {
          scene: "business_proposal",
          style: "editorial_park",
          brief: { topic: "Buffer Park", purpose: "proposal" },
          slides: [
            {
              index: 1,
              role: "section",
              title: "Market Context",
              subtitle: "A lifestyle destination anchored in local demand",
              body_blocks: ["Stable growth", "Cautious consumers"]
            },
            {
              index: 2,
              role: "content",
              layout: "metric_cards",
              title: "Demand Signals",
              body_blocks: ["GDP: 5.0%", "Retail: RMB 50.12 trillion", "Tourism: 6.5 billion trips"]
            }
          ]
        },
        template: {
          id: "business_proposal_editorial",
          theme: {
            fontFace: "Aptos",
            titleFontFace: "Georgia",
            bodyFontFace: "Aptos",
            titleColor: "F4EFE6",
            bodyColor: "D8D0C2",
            accentColor: "C47A32",
            secondaryAccentColor: "8FB8A6",
            backgroundColor: "10251E",
            surfaceColor: "18352B",
            cardColor: "F4EFE6",
            cardTextColor: "17241E"
          },
          layouts: []
        },
        assets: []
      })
    );

    await execFileAsync("node", [
      path.join(packageRoot, "src", "render.mjs"),
      "--input",
      inputPath,
      "--output",
      outputPath,
      "--manifest",
      manifestPath
    ]);

    const slide1Xml = await execFileAsync("unzip", ["-p", outputPath, "ppt/slides/slide1.xml"]);
    const slide2Xml = await execFileAsync("unzip", ["-p", outputPath, "ppt/slides/slide2.xml"]);
    expect(slide1Xml.stdout).toContain('val="10251E"');
    expect(slide1Xml.stdout).toContain('typeface="Georgia"');
    expect(slide1Xml.stdout).toContain("Market Context");
    expect(slide2Xml.stdout).toContain("Demand Signals");
    expect(slide2Xml.stdout).toContain("RMB 50.12 trillion");
  });

  it("renders two-column editorial slides with a supplied image panel", async () => {
    const workDir = path.join(tmpdir(), `ya-pptx-renderer-two-column-image-${Date.now()}`);
    await mkdir(workDir, { recursive: true });
    const imagePath = path.join(workDir, "panel.png");
    const inputPath = path.join(workDir, "input.json");
    const outputPath = path.join(workDir, "out.pptx");
    const manifestPath = path.join(workDir, "manifest.json");
    await writeFile(
      imagePath,
      Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC",
        "base64"
      )
    );

    await writeFile(
      inputPath,
      JSON.stringify({
        plan: {
          scene: "business_proposal",
          style: "editorial_park",
          brief: { topic: "Buffer Park", purpose: "proposal" },
          slides: [
            {
              index: 1,
              role: "content",
              layout: "two_column",
              title: "Warehouse Renewal Model",
              body_blocks: ["Campus demand", "Hotel dwell time", "One-card retention", "Tenant support"],
              visual_slots: [{ name: "site", kind: "image", source_path: imagePath }]
            }
          ]
        },
        template: {
          id: "business_proposal_editorial",
          theme: {
            titleFontFace: "Georgia",
            bodyFontFace: "Aptos",
            titleColor: "F4EFE6",
            bodyColor: "D8D0C2",
            accentColor: "C47A32",
            backgroundColor: "10251E",
            surfaceColor: "18352B",
            cardColor: "F4EFE6",
            cardTextColor: "17241E"
          },
          layouts: []
        },
        assets: []
      })
    );

    await execFileAsync("node", [
      path.join(packageRoot, "src", "render.mjs"),
      "--input",
      inputPath,
      "--output",
      outputPath,
      "--manifest",
      manifestPath
    ]);

    const mediaList = await execFileAsync("unzip", ["-l", outputPath]);
    expect(mediaList.stdout).toContain("ppt/media/");
    expect(mediaList.stdout).toMatch(/ppt\/media\/image/);
  });

  it("renders blue-green consulting hub-spoke and party roles layouts", async () => {
    const workDir = path.join(tmpdir(), `ya-pptx-renderer-bluegreen-${Date.now()}`);
    await mkdir(workDir, { recursive: true });
    const inputPath = path.join(workDir, "input.json");
    const outputPath = path.join(workDir, "out.pptx");
    const manifestPath = path.join(workDir, "manifest.json");

    await writeFile(
      inputPath,
      JSON.stringify({
        plan: {
          scene: "business_proposal",
          style: "consulting_report",
          brief: { topic: "Cooperation Proposal", purpose: "proposal" },
          slides: [
            {
              index: 1,
              role: "cover",
              title: "Cooperation Proposal",
              subtitle: "Business Proposal / Consulting Report",
              body_blocks: ["Blue-green project cooperation template"]
            },
            {
              index: 2,
              role: "content",
              layout: "hub_spoke",
              title: "Business ecosystem",
              body_blocks: [
                "Center: One-card system",
                "Dining traffic",
                "Hotel dwell time",
                "Gym membership",
                "Retail tenants",
                "Weekend events",
                "Data retention"
              ]
            },
            {
              index: 3,
              role: "content",
              layout: "party_roles",
              title: "Partner responsibilities",
              body_blocks: [
                "Party A: site renovation and property operations",
                "Party B: brand activation and tenant recruitment",
                "Party C: digital membership platform",
                "Party D: event planning and community relations"
              ]
            }
          ]
        },
        template: {
          id: "business_proposal_bluegreen",
          theme: {
            fontFace: "Microsoft YaHei",
            titleFontFace: "Microsoft YaHei",
            bodyFontFace: "Microsoft YaHei",
            titleColor: "333333",
            bodyColor: "333333",
            accentColor: "036EB8",
            secondaryAccentColor: "34BF49",
            backgroundColor: "FFFFFF",
            surfaceColor: "F6FAFD",
            cardColor: "FFFFFF",
            cardTextColor: "333333"
          },
          layouts: []
        },
        assets: []
      })
    );

    await execFileAsync("node", [
      path.join(packageRoot, "src", "render.mjs"),
      "--input",
      inputPath,
      "--output",
      outputPath,
      "--manifest",
      manifestPath
    ]);

    const coverXml = await execFileAsync("unzip", ["-p", outputPath, "ppt/slides/slide1.xml"]);
    const hubXml = await execFileAsync("unzip", ["-p", outputPath, "ppt/slides/slide2.xml"]);
    const rolesXml = await execFileAsync("unzip", ["-p", outputPath, "ppt/slides/slide3.xml"]);
    expect(coverXml.stdout).toContain('val="036EB8"');
    expect(coverXml.stdout).toContain('val="34BF49"');
    expect(coverXml.stdout).toContain("Cooperation Proposal");
    expect(hubXml.stdout).toContain("One-card system");
    expect(hubXml.stdout).toContain("Dining traffic");
    expect(rolesXml.stdout).toContain("Partner responsibilities");
    expect(rolesXml.stdout).toContain("Party A");
    expect(rolesXml.stdout).toContain("Party D");
  });
});
