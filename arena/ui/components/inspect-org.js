// Organization Inspector: overview, partners, threads, and trust.
import { html, useState } from "../preact.js";
import { agentLabel, orgLabel, orgStats, orgTrust, pairScope, partnerRows, scopeThreads } from "../lib/inspect.js";
import { companyColor } from "../palette.js";
import { Chip, Section, Stat } from "./cards.js";
import { Capped, useTabs } from "./inspector.js";

const time = (ts) => (ts ? new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }) : "—");
const STATUS_TONE = { verdict: "ok", closed: "neutral", open: "info" };

export function ThreadRows({ store, state, rows }) {
  if (!rows.length) return html`<p class="muted">No threads.</p>`;
  return html`<${Capped} rows=${rows} render=${(t) => html`<div class="item-row" key=${t.id}>
    <button class="link" onClick=${() => store.select({ inspect: { kind: "thread", id: t.id } })}>${t.id} ${t.title}</button>
    <${Chip} tone=${STATUS_TONE[t.status]}>${t.status}<//>
    <span class="muted small">owner ${agentLabel(state, t.owner)} · ${t.participants.length} agents · ${t.count} msgs
      ${t.duration != null ? ` · ${t.duration} s` : ""}</span></div>`} />`;
}

function Overview({ store, state, scope }) {
  const s = orgStats(state, scope.domain);
  return html`<div>
    <${Section} title="Organization" tone=${s.failed ? "bad" : companyColor(scope.domain)}>
      <div>Sector <${Chip}>${s.sector}<//> · domain <code>${scope.domain}</code>
        ${s.failed ? html` <${Chip} tone="bad">failed verification<//>` : null}</div>
      ${s.failed ? html`<div class="small">${(s.agents[0]?.reasons || []).map((r) => html`<${Chip} tone="bad">${r}<//>`)}</div>` : null}
    <//>
    <${Section} title="Activity" tone="info">
      <div class="tiles"><${Stat} label="out" value=${s.out} /><${Stat} label="in" value=${s.in} />
        <${Stat} label="threads opened" value=${s.threadsOpened} />
        <${Stat} label="tasks done" value=${s.tasks.completed} /></div>
      <div class="small">Tasks working ${s.tasks.working} · rejected or canceled ${s.tasks.rejected}</div>
    <//>
    <${Section} title="Agents" tone="neutral">${s.agents.map((a) => html`<div class="item-row" key=${a.id}>
      <button class="link" onClick=${() => store.select({ inspect: { kind: "agent", id: a.id }, tab: "overview" })}>${agentLabel(state, a.id)}</button>
      <${Chip}>${a.model === "sonnet" ? "Sonnet" : "Haiku"}<//><${Chip}>${a.role}<//>
      <${Chip} tone=${a.status === "verified" ? "ok" : a.status === "failed" ? "bad" : "pending"}>${a.status}<//>
      <span class="muted small">sent ${a.counters.sent} · received ${a.counters.received}</span></div>`)}<//>
  </div>`;
}

const COLUMNS = [["organization", "Partner"], ["out", "Out"], ["in", "In"], ["threads", "Threads"],
  ["last", "Last"], ["declines", "Decl."], ["trustFailures", "Trust ✕"]];

function Partners({ store, state, scope }) {
  const [sort, setSort] = useState(["out", -1]);
  const rows = partnerRows(state, scope.domain).sort((x, y) => {
    const [k, dir] = sort;
    const a = k === "out" ? x.out + x.in : x[k];
    const b = k === "out" ? y.out + y.in : y[k];
    return (a > b ? 1 : a < b ? -1 : 0) * dir;
  });
  if (!rows.length) return html`<p class="muted">No messages with other organizations in this range.</p>`;
  return html`<table class="grid"><tr>${COLUMNS.map(([k, label]) => html`<th class="sortable"
    onClick=${() => setSort([k, sort[0] === k ? -sort[1] : -1])}>${label}${sort[0] === k ? (sort[1] < 0 ? " ▾" : " ▴") : ""}</th>`)}</tr>
    ${rows.map((r) => html`<tr class="row" key=${r.domain}
      onClick=${() => store.select({ inspect: pairScope(scope.domain, r.domain, "org") })}>
      <td>${r.organization}<div class="muted small">${r.domain}</div></td><td>${r.out}</td><td>${r.in}</td>
      <td>${r.threads}</td><td>${time(r.last)}</td>
      <td>${r.declines ? html`<${Chip} tone="bad">${r.declines}<//>` : 0}</td>
      <td>${r.trustFailures ? html`<${Chip} tone="bad">${r.trustFailures}<//>` : 0}</td></tr>`)}
  </table>`;
}

function Trust({ store, state, scope }) {
  const t = orgTrust(state, scope.domain);
  const name = (id) => agentLabel(state, id);
  const row = (x) => html`<div class="item-row"><${Chip} tone="bad">failed<//>
    ${name(x.checker)} checked ${name(x.sender)} <span class="muted small">(${orgLabel(state, state.agents[x.sender]?.domain || "")})</span>
    <span class="muted small">${x.reason}</span></div>`;
  return html`<div>
    <${Section} title="Failed checks on this organization" tone=${t.against.length ? "bad" : "ok"}>
      ${t.against.length ? t.against.map(row) : html`<p class="muted">None.</p>`}<//>
    <${Section} title="Failed checks by this organization" tone=${t.by.length ? "bad" : "ok"}>
      ${t.by.length ? t.by.map(row) : html`<p class="muted">None.</p>`}<//>
    <${Section} title="DNS and key pins" tone="purple">${t.pins.map((p) => html`<div class="item-row">
      <button class="link" onClick=${() => store.select({ inspect: { kind: "agent", id: p.id }, tab: "overview" })}>${name(p.id)}</button>
      <${Chip} tone=${p.status === "verified" ? "ok" : p.status === "failed" ? "bad" : "pending"}>${p.status}<//>
      <span class="muted small">DNS ${p.dns} · registry checks ${p.checks}</span>
      ${p.reasons.map((r) => html`<${Chip} tone="bad">${r}<//>`)}</div>`)}<//>
  </div>`;
}

export function OrgPanel({ store, state, scope }) {
  const [tab, bar] = useTabs([["overview", "Overview"], ["partners", "Partners"], ["threads", "Threads"], ["trust", "Trust"]]);
  return html`<div>${bar}
    ${tab === "overview" ? html`<${Overview} store=${store} state=${state} scope=${scope} />` : null}
    ${tab === "partners" ? html`<${Partners} store=${store} state=${state} scope=${scope} />` : null}
    ${tab === "threads" ? html`<${ThreadRows} store=${store} state=${state} rows=${scopeThreads(state, scope)} />` : null}
    ${tab === "trust" ? html`<${Trust} store=${store} state=${state} scope=${scope} />` : null}
  </div>`;
}
