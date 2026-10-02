// Agent drawer: sectioned cards (even borders, light fills), larger type.
import { html, useEffect, useState } from "../preact.js";
import { getJson } from "../api.js";
import { liveDataAvailable } from "../store.js";
import { companyColor } from "../palette.js";
import { Chip, CodeBox, Section, Stat } from "./cards.js";
import { Checks, StepChips } from "./steps.js";

const TABS = [["overview", "Overview"], ["card", "Card"], ["prompts", "Prompts"],
  ["activity", "Activity"], ["discovery", "Discovery"]];
const REPLAY_ONLY = html`<p class="muted">Not available in replay.</p>`;
const STATE_TONE = { running: "ok", paused: "pending", stopped: "neutral" };

export function extensionParams(card) {
  const exts = card?.capabilities?.extensions || [];
  return (exts.find((e) => e.params && e.params.id) || {}).params || {};
}

function useLiveDetail(agent, mode) {
  const [detail, setDetail] = useState(null);
  useEffect(() => {
    setDetail(null);
    if (!liveDataAvailable(mode)) return undefined;
    let stop = false;
    const load = () => getJson(`/arena/agents/${agent.slug}`).then((d) => !stop && setDetail(d)).catch(() => {});
    load();
    const timer = setInterval(load, 5000);
    return () => { stop = true; clearInterval(timer); };
  }, [agent.slug, mode]);
  return detail;
}

function Overview({ agent, live }) {
  const c = live?.counters || agent.counters;
  const dns = agent.steps.dns?.detail;
  const fp = agent.steps.identity?.detail?.fingerprint;
  return html`<div>
    <${Section} title="Activity" tone=${companyColor(agent.domain)}>
      <div class="tiles"><${Stat} label="sent" value=${c.sent} /><${Stat} label="received" value=${c.received} />
        <${Stat} label="rejected" value=${c.rejected} /><${Stat} label="errors" value=${c.errors} /></div>
      <div class="small" style="margin-top:6px">State ${live ? html`<${Chip} tone=${STATE_TONE[live.state] || "neutral"}>${live.state}<//>` : html`<${Chip}>replay<//>`}
        · cadence ${agent.cadence ? `${agent.cadence[0]}–${agent.cadence[1]} s` : "—"}</div>
    <//>
    <${Section} title="Role" tone="info">
      <div>Capability <${Chip} tone="info">${agent.capability}<//> · sector <${Chip}>${agent.sector}<//> · role <${Chip}>${agent.role}<//></div>
      <div style="margin-top:4px">Needs ${agent.needs.length ? agent.needs.map((n) => html`<${Chip} tone="purple">${n}<//>`) : "—"}</div>
    <//>
    <${Section} title="Registration" tone=${agent.status === "verified" ? "ok" : agent.status === "failed" ? "bad" : "pending"}>
      <${StepChips} agent=${agent} />
    <//>
    <${Section} title="Identity" tone="purple">
      <div class="muted small">DID</div><${CodeBox} text=${agent.did || "—"} />
      <div class="muted small">Key fingerprint</div><${CodeBox} text=${fp || "—"} />
    <//>
    ${dns && !dns.skipped ? html`<${Section} title="DNS records" tone="info">
      <${CodeBox} text=${`SRV ${dns.srv}`} />
      <table class="kv">${(dns.txt || []).map((t) => { const [k, ...rest] = t.split("="); const v = rest.join("=");
        return html`<tr><td>${k}</td><td>${v}${k === "key" && v === fp ? html` <${Chip} tone="ok">✓ matches card<//>` : null}</td></tr>`; })}</table>
    <//>` : null}
    ${agent.steps.checks ? html`<${Section} title="Registry checks" tone=${agent.steps.checks.status === "ok" ? "ok" : "bad"}>
      <${Checks} verification=${agent.steps.checks.detail} /><//>` : null}
  </div>`;
}

function LiveCard({ agent }) {
  const [card, setCard] = useState(null);
  const [source, setSource] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let stop = false;
    setCard(null); setError("");
    getJson(`/agents/${agent.slug}/.well-known/agent-card.json`)
      .then((c) => { if (!stop) { setCard(c); setSource("live"); } })
      .catch((e) => {
        if (stop) return;
        setError(`Live card unavailable: ${e.message}`);
        getJson(`/arena/registry/agents/${agent.id}/card`)
          .then((c) => { if (!stop) { setCard(c); setSource("registry (stored)"); } }).catch(() => {});
      });
    return () => { stop = true; };
  }, [agent.slug]);
  if (!card) return html`<p class="muted">${error || "Loading…"}</p>`;
  const p = extensionParams(card);
  return html`<div>
    ${error ? html`<p class="error">${error}</p>` : null}
    <${Section} title=${`Agent Card · ${source}`} tone="info">
      <div class="big">${card.name}</div><div class="muted">${card.description}</div>
      <div class="small" style="margin-top:4px">Endpoint <code>${card.url}</code></div>
    <//>
    <${Section} title="Provider" tone=${companyColor(p.domain)}>${card.provider?.organization}
      <div class="muted small">${card.provider?.url}</div><//>
    <${Section} title="Skills" tone="purple">${(card.skills || []).map((s) => html`<${Chip} tone="purple" title=${s.description}>${s.id}<//>`)}<//>
    <${Section} title="ACDP identity" tone="ok">
      <div class="muted small">DID</div><${CodeBox} text=${p.did || "—"} />
      <div class="small">Organization <strong>${p.organization}</strong> · domain <strong>${p.domain}</strong> · model <strong>${p.model}</strong></div>
      <div class="muted small">Public key (x)</div><${CodeBox} text=${p.publicKeyJwk?.x || "—"} />
    <//>
    <details class="raw"><summary>Raw JSON</summary><${CodeBox} text=${JSON.stringify(card, null, 2)} /></details>
  </div>`;
}

function CardTab({ agent, state }) {
  if (!liveDataAvailable(state.mode)) {
    return html`<${Section} title="Agent Card" tone="pending">${REPLAY_ONLY}<p class="muted small">The current process serves different keys and cards than the replayed run. Overview shows the replayed fingerprint.</p><//>`;
  }
  return html`<${LiveCard} agent=${agent} />`;
}

function Prompts({ agent, live }) {
  const last = agent.decisions[agent.decisions.length - 1];
  return html`<div>
    <${Section} title="System prompt" tone="info"><pre class="prompt">${agent.systemPrompt || live?.system_prompt || "—"}</pre><//>
    <${Section} title="Last turn prompt" tone="purple"><pre class="prompt">${agent.lastPrompt || live?.last_prompt || "—"}</pre><//>
    <${Section} title="Last decision" tone=${last && last.outcome === "sent" ? "ok" : last && last.outcome.startsWith("rejected") ? "pending" : "neutral"}>
      ${last ? html`<${Chip} tone=${last.outcome === "sent" ? "ok" : "pending"}>${last.outcome}<//><pre class="prompt">${JSON.stringify(last.decision, null, 2)}</pre>`
        : html`<p class="muted">No decision yet.</p>`}
    <//>
  </div>`;
}

function Activity({ agent, live, state, store }) {
  const threads = state.threadOrder.map((id) => state.threads[id]).filter((t) =>
    t.owner === agent.id || state.messages.some((m) => m.kind === "message" && m.threadId === t.id
      && (m.from === agent.id || m.to === agent.id)));
  const tasks = Object.values(state.tasks).filter((t) => t.requester === agent.id || t.recipient === agent.id);
  const tone = (s) => (s === "completed" ? "ok" : s === "working" ? "pending" : "bad");
  return html`<div>
    <${Section} title="Agenda" tone="info"><div>${(agent.systemPrompt || "").split("\n\n")[0] || "—"}</div><//>
    <${Section} title="Threads" tone="info">${threads.length ? threads.map((t) => html`<div class="item-row">
      <button class="link" onClick=${() => store.select({ agent: null, thread: t.id, allThreads: false, focus: t.id })}>${t.id} ${t.title}</button>
      <${Chip}>${t.owner === agent.id ? "owner" : "participant"}<//><${Chip} tone=${t.closed ? "neutral" : "ok"}>${t.closed ? "closed" : "open"}<//>
      <span class="muted small">${t.count} msgs</span></div>`) : html`<p class="muted">None.</p>`}<//>
    <${Section} title="Pending inbox" tone="pending">${live ? (live.inbox.length ? live.inbox.map((i) => html`<div class="item-row">
      ${i.sender} <${Chip}>${i.intent}<//>${i.trust ? html`<${Chip} tone=${i.trust === "verified" ? "ok" : "bad"}>${i.trust}<//>` : null}</div>`)
      : html`<p class="muted">Empty.</p>`) : REPLAY_ONLY}<//>
    <${Section} title="Recent decisions" tone="neutral">${[...agent.decisions].reverse().map((d) => html`<div class="item-row">
      <${Chip} tone=${d.outcome === "sent" ? "ok" : d.outcome === "wait" ? "neutral" : "pending"}>${d.outcome}<//>
      ${d.decision && d.decision.to ? html`<span class="small">→ ${state.agents[d.decision.to]?.name || d.decision.to} (${d.decision.intent})</span>` : null}</div>`)}<//>
    <${Section} title="A2A tasks" tone="purple">${tasks.length ? tasks.map((t) => html`<div class="item-row">
      <${Chip} tone=${tone(t.state)}>${t.state}<//>
      ${t.requester === agent.id ? `→ ${state.agents[t.recipient]?.name || t.recipient}` : `← ${state.agents[t.requester]?.name || t.requester}`}
      <span class="muted small">${t.threadId}${t.reason ? ` · ${t.reason}` : ""}</span></div>`) : html`<p class="muted">No A2A tasks.</p>`}<//>
  </div>`;
}

function Discovery({ agent, state }) {
  const choices = state.messages.filter((m) => m.kind === "message" && m.from === agent.id && (m.lookingFor || m.whyThisPeer));
  return html`<div>
    ${[...agent.queries].reverse().map((q) => html`<${Section} title=${`Search: ${q.capability} · ${new Date(q.ts * 1000).toLocaleTimeString()}`} tone="purple">
      ${q.results.length ? q.results.map((r) => html`<div class="item-row"><${Chip} tone=${r.status === "verified" ? "ok" : r.status === "failed" ? "bad" : "neutral"}>${r.status}<//>
        ${r.name} <span class="muted small">${r.organization} · ${r.domain}</span>${r.new ? html` <${Chip} tone="purple">new<//>` : null}</div>`)
        : html`<p class="muted">No results.</p>`}<//>`)}
    <${Section} title="Choices" tone="info">${choices.length ? choices.map((m) => html`<div class="item-row">→ <strong>${state.agents[m.to]?.name || m.to}</strong>:
      <em>${m.lookingFor}</em><div class="muted small">${m.whyThisPeer}</div></div>`) : html`<p class="muted">None yet.</p>`}<//>
    <${Section} title="Trust map" tone="ok">${Object.entries(agent.trust).map(([sender, t]) => html`<div class="item-row">
      <${Chip} tone=${t.status === "verified" ? "ok" : "bad"}>${t.status}<//> ${state.agents[sender]?.name || sender}
      ${t.reason ? html`<span class="muted small">${t.reason}</span>` : null}</div>`)}<//>
  </div>`;
}

const VIEW = { overview: Overview, card: CardTab, prompts: Prompts, activity: Activity, discovery: Discovery };

export function Drawer({ store, state }) {
  const agent = state.agents[state.selection.agent];
  const live = useLiveDetail(agent || { slug: "" }, agent ? state.mode : "replay");
  if (!agent) return null;
  const tab = state.selection.tab || "overview";
  const Tab = VIEW[tab] || Overview;
  const status = agent.status === "verified" ? "ok" : agent.status === "failed" ? "bad" : "pending";
  return html`<section class="drawer">
    <header class="drawer-head">
      <span class="avatar big-avatar" style=${`background:${companyColor(agent.domain)}`}>${agent.model === "sonnet" ? "S" : "H"}</span>
      <div><div class="drawer-name">${agent.name}</div>
        <div class="muted">${agent.organization} · ${agent.domain} · ${agent.model === "sonnet" ? "Sonnet" : "Haiku"}</div></div>
      <span class="spacer"></span>
      <${Chip} tone=${status}>${agent.status}<//>
      <button aria-label="Close" onClick=${() => store.select({ agent: null })}>×</button>
    </header>
    <nav class="tabs">${TABS.map(([key, label]) => html`<button class=${tab === key ? "on" : ""}
      onClick=${() => store.select({ tab: key })}>${label}</button>`)}</nav>
    <div class="drawer-body"><${Tab} agent=${agent} live=${live} state=${state} store=${store} /></div>
  </section>`;
}
