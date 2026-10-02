// Message popup card, used on the Comms Map and in the Sequence view.
import { html } from "../preact.js";
import { companyColor } from "../palette.js";

const TONE = { decline: "var(--bad)", challenge: "var(--bad)", verdict: "var(--ok)" };

export function PopupCard({ m, state }) {
  const from = state.agents[m.from] || { name: m.from, domain: "" };
  const to = state.agents[m.to] || { name: m.to };
  const tone = TONE[m.intent] || companyColor(from.domain);
  const body = m.body.length > 100 ? `${m.body.slice(0, 100)}…` : m.body;
  return html`<div class="popup-card" style=${`--tone:${tone}`}>
    <div class="popup-head"><strong>${from.name}</strong> → ${to.name}
      <span class="pill" style=${`--tone:${tone}`}>${m.intent}</span></div>
    <div class="popup-body">${body}</div>
  </div>`;
}
