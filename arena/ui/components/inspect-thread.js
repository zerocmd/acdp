// Thread Inspector: how the thread unfolded, who took part, and every message.
import { html } from "../preact.js";
import { agentLabel, threadParticipants, threadStory } from "../lib/inspect.js";
import { Chip, CodeBox } from "./cards.js";
import { Capped, useTabs } from "./inspector.js";

const time = (ts) => new Date(ts * 1000).toLocaleTimeString();
const KIND_TONE = { opened: "info", search: "purple", closed: "ok" };

function Story({ store, state, scope }) {
  const name = (id) => agentLabel(state, id);
  const steps = threadStory(state, scope.id);
  return html`<ol class="story">${steps.map((s, i) => html`<li key=${i} class=${s.failed ? "failed" : ""}>
    <span class="muted small">${time(s.ts)}</span>
    ${s.kind === "message"
      ? html`<${Chip} tone=${s.failed ? "bad" : s.intent === "verdict" ? "ok" : s.intent === "decline" || s.intent === "challenge" ? "bad" : "info"}>${s.intent}<//>
        <button class="link" onClick=${() => store.select({ inspect: { kind: "agent", id: s.agent }, tab: "overview" })}>${name(s.agent)}</button>
        → <button class="link" onClick=${() => store.select({ inspect: { kind: "agent", id: s.to }, tab: "overview" })}>${name(s.to)}</button>:
        ${s.text}${s.failed ? html` <${Chip} tone="bad">trust failed<//>` : null}
        ${s.lookingFor ? html`<div class="intent-line">looking for: ${s.lookingFor} · why: ${s.whyThisPeer || "—"}</div>` : null}`
      : html`<${Chip} tone=${KIND_TONE[s.kind]}>${s.kind}<//> ${name(s.agent)}: ${s.text}`}
  </li>`)}</ol>`;
}

function Participants({ store, state, scope }) {
  const name = (id) => agentLabel(state, id);
  return html`<div>${threadParticipants(state, scope.id).map((p) => html`<div class="item-row" key=${p.id}>
    <button class="link" onClick=${() => store.select({ inspect: { kind: "agent", id: p.id }, tab: "overview" })}>${name(p.id)}</button>
    <span class="muted small">${state.agents[p.id]?.organization || ""}</span>
    <${Chip}>${p.broughtBy ? `brought in by ${name(p.broughtBy)}` : "joined on its own"}<//>
    <span class="muted small">sent ${p.sent} · received ${p.received}</span></div>`)}</div>`;
}

function Messages({ state, scope }) {
  const ms = state.messages.filter((m) => m.kind === "message" && m.threadId === scope.id);
  const exportJson = () => navigator.clipboard?.writeText(JSON.stringify({ thread: state.threads[scope.id], messages: ms }, null, 2));
  return html`<div><button onClick=${exportJson}>Export JSON</button>
    <${Capped} rows=${ms} render=${(m) => html`<details key=${m.id} class="raw"><summary>${time(m.ts)} · ${m.intent} · ${m.id}</summary>
      <${CodeBox} text=${JSON.stringify(m, null, 2)} /></details>`} /></div>`;
}

export function ThreadPanel({ store, state, scope }) {
  const [tab, bar] = useTabs([["story", "Story"], ["participants", "Participants"], ["messages", "Messages"]]);
  return html`<div>${bar}
    ${tab === "story" ? html`<${Story} store=${store} state=${state} scope=${scope} />` : null}
    ${tab === "participants" ? html`<${Participants} store=${store} state=${state} scope=${scope} />` : null}
    ${tab === "messages" ? html`<${Messages} state=${state} scope=${scope} />` : null}
  </div>`;
}
