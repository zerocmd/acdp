import { html } from "../preact.js";
import { chatItems } from "../store.js";

export function Chat({ state }) {
  const name = (id) => state.agents[id]?.name || id;
  return html`<div class="view scroll" style="padding:8px">
    ${chatItems(state).map((m) => m.kind === "system"
      ? html`<div class="muted">${m.text}</div>`
      : html`<div><strong>${name(m.from)} → ${name(m.to)}</strong> <span class="chip">${m.intent}</span><div>${m.body}</div></div>`)}
  </div>`;
}
