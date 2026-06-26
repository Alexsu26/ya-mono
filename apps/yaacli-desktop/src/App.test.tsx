import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App, ThinkingBlock, ToolCall } from "./App";

test("opens and closes the run context drawer", async () => {
  const user = userEvent.setup();
  render(<App />);

  const toggle = screen.getByRole("button", { name: "Open run context" });
  const drawer = screen
    .getByText("Run context")
    .closest<HTMLElement>('[aria-label="Run context"]')!;

  // Drawer is rendered but hidden (aria-hidden + inert) until opened.
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(drawer).toHaveAttribute("aria-hidden", "true");
  expect(drawer).toHaveAttribute("inert");

  await user.click(toggle);

  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(drawer).toHaveAttribute("aria-hidden", "false");
  expect(drawer).not.toHaveAttribute("inert");
});

test("thinking content is collapsed by default and expands on click", async () => {
  const user = userEvent.setup();
  render(
    <ThinkingBlock id="thinking-1" text="Inspect the repository context." />,
  );

  const toggle = screen.getByRole("button", { name: "Thinking" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(
    screen.queryByText("Inspect the repository context."),
  ).not.toBeInTheDocument();

  await user.click(toggle);

  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("Inspect the repository context.")).toBeVisible();
});

test("markdown replies render structured elements (headings, code, lists, tables)", async () => {
  const user = userEvent.setup();
  const markdown = [
    "## Heading",
    "",
    "Paragraph with `inline` code.",
    "",
    "```ts",
    "const answer = 42;",
    "```",
    "",
    "- one",
    "- two",
    "",
    "| a | b |",
    "| --- | --- |",
    "| 1 | 2 |",
  ].join("\n");

  render(<ThinkingBlock id="thinking-md" text={markdown} />);

  await user.click(screen.getByRole("button", { name: "Thinking" }));

  // Heading becomes a real <h2>, not bare text.
  expect(
    screen.getByRole("heading", { level: 2, name: "Heading" }),
  ).toBeVisible();
  // Fenced code block is wrapped with a language label + copy button, and the
  // inner <code> carries highlight.js tokenization (class "hljs").
  expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  const codeBlock = document.querySelector(".code-block");
  expect(codeBlock).not.toBeNull();
  expect(codeBlock?.textContent).toContain("const answer = 42");
  expect(codeBlock?.querySelector("pre code.hljs")).not.toBeNull();
  // Inline code survives (separate from the fenced block).
  expect(screen.getByText("inline")).toBeInTheDocument();
  // GFM list and table render structured elements.
  expect(screen.getByText("one")).toBeInTheDocument();
  expect(screen.getByText("two")).toBeInTheDocument();
  expect(document.querySelector("table")).not.toBeNull();
});

test("tool calls stay collapsed with the result hidden until expanded", async () => {
  const user = userEvent.setup();
  render(
    <ToolCall
      block={{
        id: "tool-1",
        type: "tool",
        runId: "run-1",
        toolCallId: "tc-1",
        name: "list_files",
        args: { path: "apps/yacli-desktop" },
        result: '[{"name":"README.md","type":"file"}]',
        status: "completed",
      }}
    />,
  );

  // Name + arg summary are visible; the raw result is not.
  expect(screen.getByText("list_files")).toBeInTheDocument();
  expect(screen.queryByText(/README\.md/)).not.toBeInTheDocument();

  await user.click(screen.getByRole("button"));

  // Result is revealed only after expanding.
  expect(screen.getByText(/README\.md/)).toBeInTheDocument();
});
