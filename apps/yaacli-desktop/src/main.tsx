import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource/geist-sans/latin-400.css";
import "@fontsource/geist-sans/latin-500.css";
import "@fontsource/geist-sans/latin-600.css";
import "@fontsource/geist-mono/latin-400.css";
import "@fontsource/geist-mono/latin-500.css";

import { App } from "./App";
import "./styles.css";

// Dark is the product default; the user can switch to light via Settings,
// which sets data-theme and persists it through the sidecar config.
if (!document.documentElement.dataset.theme) {
  document.documentElement.dataset.theme = "dark";
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
