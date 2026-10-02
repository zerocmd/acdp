// A− / A+ control. Scales every font through --text-scale; remembered per browser.
import { html, useEffect, useState } from "../preact.js";
import { clampScale, stepScale } from "../lib/textscale.js";

const KEY = "arena.textScale";

function load() {
  try { return clampScale(localStorage.getItem(KEY) ?? 1); } catch { return 1; }
}

export function TextSize() {
  const [scale, setScale] = useState(load);
  useEffect(() => {
    document.documentElement.style.setProperty("--text-scale", String(scale));
    try { localStorage.setItem(KEY, String(scale)); } catch { /* private mode: keep for this session */ }
  }, [scale]);
  return html`<span class="textsize" title="Text size (double-click to reset)" onDblClick=${() => setScale(1)}>
    <button onClick=${() => setScale((s) => stepScale(s, -1))} aria-label="Smaller text">A−</button>
    <button onClick=${() => setScale((s) => stepScale(s, 1))} aria-label="Larger text">A+</button>
  </span>`;
}
