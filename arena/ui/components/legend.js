import { html } from "../preact.js";

export function Legend() {
  return html`<details class="legend">
    <summary>Legend</summary>
    <div><span class="swatch" style="background:var(--ok)"></span>verified</div>
    <div><span class="swatch" style="background:var(--pending)"></span>pending</div>
    <div><span class="swatch" style="background:var(--bad)"></span>failed / decline / challenge</div>
    <div><span class="swatch" style="background:var(--search)"></span>discovery search</div>
    <div><span class="badge">S</span> Sonnet · <span class="badge">H</span> Haiku</div>
    <div class="muted">Edge color = thread · width = messages</div>
  </details>`;
}
