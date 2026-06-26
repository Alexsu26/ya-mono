import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

import { CodeBlock } from "./components/CodeBlock";

/**
 * Shared ReactMarkdown configuration for assistant text and thinking blocks.
 * `remarkGfm` adds tables/strikethrough/task-lists/autolinks; `rehypeHighlight`
 * adds highlight.js token spans (unknown languages are skipped, not fatal).
 *
 * ReactMarkdown itself is imported directly in components that render it, to
 * keep this a pure config module (no component exports).
 */
export const markdownRemarkPlugins = [remarkGfm];
export const markdownRehypePlugins = [rehypeHighlight];

export const markdownComponents: Components = {
  pre: CodeBlock,
};
