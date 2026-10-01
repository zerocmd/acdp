import { html } from "../preact.js";

export function ViewSwitch({ store, state, views }) {
  return html`<div class="viewswitch">
    ${Object.entries(views).map(([key, [label]]) => html`<button
      class=${state.selection.view === key ? "on" : ""}
      onClick=${() => store.select({ view: key })}>${label}</button>`)}
    <span class="spacer"></span>
    ${state.selection.range ? html`<button onClick=${() => store.select({ range: null })}>Clear time range</button>` : null}
  </div>`;
}
