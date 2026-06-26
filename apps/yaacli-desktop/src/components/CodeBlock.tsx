import {
  useState,
  type ComponentPropsWithoutRef,
  type ReactElement,
  type ReactNode,
} from "react";
import { Check, Copy } from "lucide-react";

/**
 * Code block renderer used by ReactMarkdown. rehype-highlight runs before the
 * component mapping, so the `<code>` child already carries `hljs` token spans;
 * we only add a top bar with a language label and a copy button.
 */

function extractLanguage(className: unknown): string {
  if (typeof className !== "string" || !className) return "";
  const match = /language-([\w-]+)/.exec(className);
  return match ? match[1] : "";
}

function nodeToText(node: ReactNode): string {
  if (node == null || node === false || node === true) return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeToText).join("");
  if (typeof node === "object" && "props" in (node as ReactElement)) {
    return nodeToText(
      (node as ReactElement<{ children?: ReactNode }>).props.children,
    );
  }
  return "";
}

export function CodeBlock({ children }: ComponentPropsWithoutRef<"pre">) {
  const [copied, setCopied] = useState(false);

  const codeElement = (Array.isArray(children) ? children[0] : children) as
    | ReactElement<{ className?: string; children?: ReactNode }>
    | undefined;
  const className = codeElement?.props?.className;
  const language = extractLanguage(className);
  const rawText = nodeToText(codeElement?.props?.children).replace(/\n$/, "");

  const copy = async () => {
    if (!rawText) return;
    try {
      await navigator.clipboard.writeText(rawText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — ignore */
    }
  };

  return (
    <div className="code-block">
      <div className="code-block-bar">
        <span className="code-block-lang">{language || "text"}</span>
        <button
          className={`copy-button${copied ? " copied" : ""}`}
          onClick={copy}
          type="button"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>{children}</pre>
    </div>
  );
}
