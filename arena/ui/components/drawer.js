import { html, useEffect, useState } from "../preact.js";
import { getJson } from "../api.js";
import { companyColor } from "../palette.js";
import { Stepper } from "./steps.js";

const TABS = [["overview", "Overview"], ["card", "Card"], ["prompts", "Prompts"],
  ["activity", "Activity"], ["discovery", "Discovery"]];
const REPLAY_ONLY = html`<p class="muted">Not available in replay.</p>`;

export function extensionParams(card) {
  const exts = card?.capabilities?.extensions || [];
  return (exts.find((e) => e.params && e.params.id) || {}).params || {};
}

function useLiveDetail(agent, mode) {
  const [detail, setDetail] = useState(null);
  useEffect(() => {
    setDetail(null);
    if (mode === "replay") return undefined;
    let stop = false;
    const load = () => getJson(`/arena/agents/${agent.slug}`).then((d) => !stop && setDetail(d)).catch(() => {});
    load();
    const timer = setInterval(load, 5000);
    return () => { stop = true; clearInterval(timer); };
  }, [agent.slug, mode]);
  return detail;
}

function Overview({ agent, live, state }) {
  const counters = live?.counters || agent.counters;
  return html`<div>
    <dl class="facts">
      <dt>Role</dt><dd>${agent.role}</dd>
      <dt>Capability</dt><dd>${agent.capability}</dd>
      <dt>Needs</dt><dd>${agent.needs.join(", ") || "—"}</dd>
      <dt>Cadence</dt><dd>${agent.cadence ? `${agent.cadence[0]}–${agent.cadence[1]} s` : "—"}</dd>
      <dt>State</dt><dd>${live ? live.state : state.mode === "replay" ? "replay" : "—"}</dd>
      <dt>Counters</dt><dd>sent ${counters.sent} · received ${counters.received} · rejected ${counters.rejected} · errors ${counters.errors}</dd>
    </dl>
    <h4>Registration</h4>
    <${Stepper} agent=${agent} />
  </div>`;
}

function CardTab({ agent }) {
  const [card, setCard] = useState(null);
  const [source, setSource] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    setCard(null); setError("");
    getJson(`/agents/${agent.slug}/.well-known/agent-card.json`)
      .then((c) => { setCard(c); setSource("live"); })
      .catch((e) => {
        setError(`Live card unavailable: ${e.message}`);
        getJson(`/arena/registry/agents/${agent.id}/card`)
          .then((c) => { setCard(c); setSource("registry (stored)"); })
          .catch(() => {});
      });
  }, [agent.slug]);
  if (!card) return html`<p class="muted">${error || "Loading…"}</p>`;
  const p = extensionParams(card);
  return html`<div>
    ${error ? html`<p class="error">${error}</p>` : null}
    <p class="muted">Source: ${source}</p>
    <dl class="facts">
      <dt>Name</dt><dd>${card.name}</dd>
      <dt>Provider</dt><dd>${card.provider?.organization}</dd>
      <dt>URL</dt><dd><code>${card.url}</code></dd>
      <dt>Skills</dt><dd>${(card.skills || []).map((s) => s.id).join(", ")}</dd>
      <dt>DID</dt><dd><code>${p.did}</code></dd>
      <dt>Domain</dt><dd>${p.domain}</dd>
      <dt>Key (x)</dt><dd><code>${p.publicKeyJwk?.x}</code></dd>
      <dt>Model</dt><dd>${p.model}</dd>
    </dl>
    <button onClick=${() => navigator.clipboard?.writeText(JSON.stringify(card, null, 2))}>Copy JSON</button>
    <pre>${JSON.stringify(card, null, 2)}</pre>
  </div>`;
}

function Prompts({ agent, live }) {
  const last = agent.decisions[agent.decisions.length - 1];
  return html`<div>
    <h4>System prompt</h4><pre>${agent.systemPrompt || live?.system_prompt || "—"}</pre>
    <h4>Last turn prompt</h4><pre>${agent.lastPrompt || live?.last_prompt || "—"}</pre>
    <h4>Last decision</h4>
    ${last ? html`<p>Outcome: <strong>${last.outcome}</strong></p><pre>${JSON.stringify(last.decision, null, 2)}</pre>`
      : html`<p class="muted">No decision yet.</p>`}
  </div>`;
}

function Activity({ agent, live, state, store }) {
  const threads = state.threadOrder.map((id) => state.threads[id]).filter((t) =>
    t.owner === agent.id || state.messages.some((m) => m.kind === "message" && m.threadId === t.id
      && (m.from === agent.id || m.to === agent.id)));
  return html`<div>
    <h4>Agenda</h4><pre>${(agent.systemPrompt || "").split("\n\n")[0] || "—"}</pre>
    <h4>Threads</h4>
    <ul>${threads.map((t) => html`<li><button class="link" onClick=${() => store.select({ agent: null, thread: t.id, allThreads: false })}>
      ${t.id} ${t.title}</button> <span class="muted">${t.owner === agent.id ? "owner" : "participant"} · ${t.closed ? "closed" : "open"} · ${t.count} msgs</span></li>`)}</ul>
    <h4>Pending inbox</h4>
    ${live ? html`<ul>${live.inbox.map((i) => html`<li>${i.sender} · ${i.intent} · ${i.trust || "—"}</li>`)}</ul>${live.inbox.length ? null : html`<p class="muted">Empty.</p>`}`
      : REPLAY_ONLY}
    <h4>Recent decisions</h4>
    <ul>${[...agent.decisions].reverse().map((d) => html`<li><span class="chip">${d.outcome}</span>
      ${d.decision ? html` ${d.decision.action}${d.decision.to ? ` → ${d.decision.to}` : ""}${d.decision.intent ? ` (${d.decision.intent})` : ""}` : null}</li>`)}</ul>
  </div>`;
}

function Discovery({ agent, state }) {
  const choices = state.messages.filter((m) => m.kind === "message" && m.from === agent.id && (m.lookingFor || m.whyThisPeer));
  return html`<div>
    <h4>Queries</h4>
    ${[...agent.queries].reverse().map((q) => html`<div class="query">
      <div><strong>${q.capability}</strong> <span class="muted">${new Date(q.ts * 1000).toLocaleTimeString()}</span></div>
      <ul>${q.results.map((r) => html`<li><span class=${`dot ${r.status}`}></span> ${r.name}
        <span class="muted">${r.organization} · ${r.domain}</span>${r.new ? html` <span class="chip new">new</span>` : null}</li>`)}</ul>
      ${q.results.length ? null : html`<p class="muted">No results.</p>`}
    </div>`)}
    <h4>Choices</h4>
    <ul>${choices.map((m) => html`<li>→ ${state.agents[m.to]?.name || m.to}: <em>${m.lookingFor}</em><div class="muted">${m.whyThisPeer}</div></li>`)}</ul>
    <h4>Trust map</h4>
    <ul>${Object.entries(agent.trust).map(([sender, t]) => html`<li><span class=${`dot ${t.status}`}></span>
      ${state.agents[sender]?.name || sender} <span class="muted">${t.status}${t.reason ? ` · ${t.reason}` : ""}</span></li>`)}</ul>
  </div>`;
}

const VIEW = { overview: Overview, card: CardTab, prompts: Prompts, activity: Activity, discovery: Discovery };

export function Drawer({ store, state }) {
  const agent = state.agents[state.selection.agent];
  const live = useLiveDetail(agent || { slug: "" }, agent ? state.mode : "replay");
  if (!agent) return null;
  const tab = state.selection.tab || "overview";
  const Tab = VIEW[tab] || Overview;
  return html`<section class="drawer">
    <header class="drawer-head">
      <span class="avatar" style=${`background:${companyColor(agent.domain)}`}>${agent.model === "sonnet" ? "S" : "H"}</span>
      <div><strong>${agent.name}</strong> · ${agent.organization}
        <div class="muted">${agent.id} · ${agent.model} · <span class=${agent.status === "verified" ? "ok" : agent.status === "failed" ? "bad" : ""}>${agent.status}</span></div></div>
      <span class="spacer"></span>
      <button aria-label="Close" onClick=${() => store.select({ agent: null })}>×</button>
    </header>
    <nav class="tabs">${TABS.map(([key, label]) => html`<button class=${tab === key ? "on" : ""}
      onClick=${() => store.select({ tab: key })}>${label}</button>`)}</nav>
    <div class="drawer-body"><${Tab} agent=${agent} live=${live} state=${state} store=${store} /></div>
  </section>`;
}
