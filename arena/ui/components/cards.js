// Shared card and chip pieces. Even borders, light fills (no one-sided borders).
import { html } from "../preact.js";

export const TONES = { ok: "var(--ok)", bad: "var(--bad)", pending: "var(--pending)",
  info: "var(--accent)", neutral: "var(--line)", purple: "var(--search)" };

export function Section({ title, tone = "neutral", children }) {
  return html`<section class="sec" style=${`--tone:${TONES[tone] || tone}`}>
    ${title ? html`<div class="sec-title">${title}</div>` : null}
    <div class="sec-body">${children}</div>
  </section>`;
}

export function Chip({ tone = "neutral", title, children }) {
  return html`<span class="pill" title=${title || ""} style=${`--tone:${TONES[tone] || tone}`}>${children}</span>`;
}

export function Stat({ label, value }) {
  return html`<div class="tile"><b>${value}</b>${label}</div>`;
}

export function CodeBox({ text }) {
  return html`<div class="codebox"><code>${text}</code>
    <button title="Copy" onClick=${() => navigator.clipboard?.writeText(String(text))}>Copy</button></div>`;
}
