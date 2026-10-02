// Pair Inspector: the conversation between two agents or two organizations.
import { html } from "../preact.js";
import { agentLabel, pairStats } from "../lib/inspect.js";
import { companyColor, threadColor } from "../palette.js";
import { Chip, Section, Stat } from "./cards.js";
import { Capped, useTabs } from "./inspector.js";

const time = (ts) => new Date(ts * 1000).toLocaleTimeString();
const TASK_TONE = { completed: "ok", working: "pending" };

function Bubble({ m, state }) {
  const from = state.agents[m.from] || { name: m.from, domain: "" };
  const to = state.agents[m.to] || { name: m.to };
  const failed = m.trust && m.trust.status !== "verified";
  return html`<div class="msg" key=${m.id}>
    <span class="avatar" style=${`background:${companyColor(from.domain)}`}>${from.model === "sonnet" ? "S" : "H"}</span>
    <div class="msg-main"><div class="msg-head"><strong>${agentLabel(state, m.from)}</strong>
      <span class="muted">→ ${agentLabel(state, m.to)} · ${time(m.ts)}</span></div>
      <div class=${`bubble${failed ? " failed" : ""}`}>${m.body}</div>
      <div class="msg-chips"><${Chip} tone=${m.intent === "decline" || m.intent === "challenge" ? "bad" : m.intent === "verdict" ? "ok" : "info"}>${m.intent}<//>
        ${m.trust ? html`<${Chip} tone=${failed ? "bad" : "ok"}>${failed ? `✕ ${m.trust.reason}` : "✓ verified"}<//>` : null}</div>
      ${m.lookingFor || m.whyThisPeer ? html`<div class="intent-line">looking for: ${m.lookingFor || "—"} · why: ${m.whyThisPeer || "—"}</div>` : null}
    </div></div>`;
}

function Conversation({ store, state, stats }) {
  if (!stats.messages.length) return html`<p class="muted">No messages between these two in this range.</p>`;
  return html`<div>${stats.threads.map((id) => {
    const t = state.threads[id];
    const ms = stats.messages.filter((m) => m.threadId === id);
    return html`<div key=${id}><button class="chip-btn" style=${`--tc:${threadColor(t?.color ?? 0)}`}
        onClick=${() => store.select({ inspect: { kind: "thread", id } })}>${id} ${t?.title || ""} · ${ms.length}</button>
      <${Capped} rows=${ms} render=${(m) => html`<${Bubble} m=${m} state=${state} />`} /></div>`;
  })}</div>`;
}

function Timeline({ scope, state, stats }) {
  const ms = stats.messages;
  if (!ms.length) return html`<p class="muted">No messages.</p>`;
  const t0 = ms[0].ts;
  const span = Math.max(1, ms[ms.length - 1].ts - t0);
  const W = 360;
  const side = (id) => (scope.level === "org" ? state.agents[id]?.domain : id);
  const y = (id) => (side(id) === scope.a ? 20 : 60);
  return html`<div>
    <svg class="pair-strip" width=${W + 20} height="80">
      <line x1="10" x2=${W + 10} y1="20" y2="20" class="lane-axis" /><line x1="10" x2=${W + 10} y1="60" y2="60" class="lane-axis" />
      ${ms.map((m) => { const x = 10 + ((m.ts - t0) / span) * W; return html`<line key=${m.id} class=${`pair-arrow ${m.intent}`}
        x1=${x} x2=${x} y1=${y(m.from)} y2=${y(m.to)}><title>${m.intent} · ${time(m.ts)}</title></line>`; })}
    </svg>
    <div class="tiles"><${Stat} label="requests answered" value=${stats.responses.length} />
      <${Stat} label="median s" value=${stats.median ?? "—"} /><${Stat} label="slowest s" value=${stats.slowest ?? "—"} />
      <${Stat} label="declines" value=${stats.declines} /></div>
    ${stats.responses.map((r) => html`<div class="small item-row" key=${r.id}>request ${r.id} answered in ${r.seconds} s</div>`)}
  </div>`;
}

function TrustTasks({ state, stats }) {
  const name = (id) => agentLabel(state, id);
  return html`<div>
    <${Section} title="A2A tasks" tone="purple">${stats.tasks.length ? stats.tasks.map((t) => html`<div class="item-row" key=${t.id}>
      <${Chip} tone=${TASK_TONE[t.state] || "bad"}>${t.state}<//> ${name(t.requester)} → ${name(t.recipient)}
      <span class="muted small">${t.threadId}${t.reason ? ` · ${t.reason}` : ""}${t.updated != null && t.created != null ? ` · ${Math.round(t.updated - t.created)} s` : ""}</span></div>`)
      : html`<p class="muted">No A2A tasks.</p>`}<//>
    <${Section} title="Trust checks" tone=${stats.checks.some((c) => c.status !== "verified") ? "bad" : "ok"}>
      ${stats.checks.length ? stats.checks.map((c) => html`<div class="item-row"><${Chip} tone=${c.status === "verified" ? "ok" : "bad"}>${c.status}<//>
        ${name(c.checker)} checked ${name(c.sender)} <span class="muted small">${c.reason}</span></div>`)
        : html`<p class="muted">No checks.</p>`}<//>
    <${Section} title="Discovery" tone="purple">${stats.finds.length ? stats.finds.map((f) => html`<div class="item-row">
      ${name(f.agent)} searched <${Chip} tone="purple">${f.capability}<//> and found ${name(f.found)}
      ${f.new ? html`<${Chip} tone="purple">new<//>` : null}<span class="muted small">${time(f.ts)}</span></div>`)
      : html`<p class="muted">No searches found the other side.</p>`}<//>
  </div>`;
}

export function PairPanel({ store, state, scope }) {
  const [tab, bar] = useTabs([["conversation", "Conversation"], ["timeline", "Timeline"], ["trust", "Trust & tasks"]]);
  const stats = pairStats(state, scope);
  return html`<div>${bar}
    ${tab === "conversation" ? html`<${Conversation} store=${store} state=${state} stats=${stats} />` : null}
    ${tab === "timeline" ? html`<${Timeline} scope=${scope} state=${state} stats=${stats} />` : null}
    ${tab === "trust" ? html`<${TrustTasks} state=${state} stats=${stats} />` : null}
  </div>`;
}
