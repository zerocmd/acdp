import { html } from "../preact.js";
import { agentsByCompany } from "../store.js";
import { companyColor } from "../palette.js";

export function Sidebar({ store, state }) {
  const all = Object.values(state.agents);
  const verified = all.filter((a) => a.status === "verified").length;
  const failed = all.filter((a) => a.status === "failed").length;
  return html`<nav class="sidebar">
    <h3>Agents</h3>
    ${agentsByCompany(state).map((group) => html`<div class="company">
      <div class="company-name" style=${`border-color:${companyColor(group.domain)}`}>
        ${group.organization}<div class="muted">${group.domain}</div>
      </div>
      ${group.agents.map((a) => html`<button
          class=${`agent-row${state.selection.agent === a.id ? " selected" : ""}`}
          onClick=${() => store.select({ agent: a.id, tab: "overview" })}>
        <span class=${`dot ${a.status}`}></span>
        <span class="badge">${a.model === "sonnet" ? "S" : "H"}</span>
        <span>${a.name}</span>
      </button>`)}
    </div>`)}
    <h3>Registry</h3>
    <button class="link" onClick=${() => store.select({ view: "registry" })}>
      ${all.length} entries · ${verified} verified · ${failed} failed
    </button>
  </nav>`;
}
