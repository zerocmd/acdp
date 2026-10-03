// Inspector: one right-column panel for an agent, an organization, a pair, or a thread.
// Each kind has a free summary built from events; with model credentials, a Haiku
// summary is one click away.
import { html, useEffect, useState } from "../preact.js";
import { getJson, postJson } from "../api.js";
import { scopeKey, scopeLabel, summarize, summaryCacheKey, summaryRequest, switchPairLevel } from "../lib/inspect.js";
import { Chip, Section } from "./cards.js";
import { Drawer } from "./drawer.js";
import { OrgPanel } from "./inspect-org.js";
import { PairPanel } from "./inspect-pair.js";
import { ThreadPanel } from "./inspect-thread.js";

const KIND_LABEL = { org: "Organization", pair: "Conversation", thread: "Thread" };
const PANELS = { org: OrgPanel, pair: PairPanel, thread: ThreadPanel };
const FLAG_LABEL = { "trust-failure": "trust failure", "task-rejected": "task rejected",
  "task-canceled": "task canceled", "impostor-contact": "impostor contact", unanswered: "unanswered request" };

let modelAvailable = null; // /arena/status for this page load
const summaries = new Map(); // summaryCacheKey -> {summary, at, count, lastSeq}

function useModelAvailable() {
  const [ok, setOk] = useState(modelAvailable);
  useEffect(() => {
    if (modelAvailable !== null) return;
    getJson("/arena/status")
      .then((s) => { modelAvailable = Boolean(s.summarize); setOk(modelAvailable); })
      .catch(() => { modelAvailable = false; setOk(false); });
  }, []);
  return Boolean(ok);
}

function SummaryCard({ state, scope }) {
  const free = summarize(state, scope);
  const key = summaryCacheKey(state, scope);
  const available = useModelAvailable();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [, setTick] = useState(0);
  const cached = summaries.get(key);
  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const body = summaryRequest(state, scope);
      const { summary } = await postJson("/arena/summarize", body);
      summaries.set(key, { summary, at: new Date(), count: body.messages.length, lastSeq: free.lastSeq });
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
    setTick((t) => t + 1);
  };
  const tone = free.flags.length ? "bad" : free.outcome === "open" ? "info" : "ok";
  return html`<${Section} title="Summary" tone=${tone}>
    <div class="sum-head">${free.headline}</div>
    ${free.opening ? html`<div class="sum-row"><span class="muted">Opening ask</span> ${free.opening.text}
      ${free.opening.lookingFor ? html` <em class="muted">(looking for: ${free.opening.lookingFor})</em>` : null}</div>` : null}
    ${free.latest ? html`<div class="sum-row"><span class="muted">Latest</span> ${free.latest.from} · ${free.latest.intent}: ${free.latest.text}</div>` : null}
    <div class="sum-row"><span class="muted">Outcome</span> ${free.outcome}</div>
    ${free.flags.length ? html`<div>${free.flags.map((f) => html`<${Chip} tone="bad">${FLAG_LABEL[f] || f}<//>`)}</div>` : null}
    ${cached ? html`<div class="sum-model">
      <div class="muted small">Haiku summary · ${cached.at.toLocaleTimeString()} · from ${cached.count} messages
        ${free.lastSeq > cached.lastSeq ? html` · <button class="link" disabled=${busy} onClick=${run}>Refresh</button>` : null}</div>
      <p>${cached.summary}</p></div>` : null}
    ${available && !cached && free.count ? html`<button disabled=${busy} onClick=${run}>${busy ? "Summarizing…" : "Summarize with Haiku"}</button>` : null}
    ${error ? html`<p class="error">${error}</p>` : null}
  <//>`;
}

function exists(state, scope) {
  if (scope.kind === "org") return Object.values(state.agents).some((a) => a.domain === scope.domain);
  if (scope.kind === "thread") return Boolean(state.threads[scope.id]);
  return true;
}

export function BackButton({ store, state }) {
  return state.selection.history.length
    ? html`<button aria-label="Back" title="Back" onClick=${() => store.back()}>←</button>` : null;
}

export function Inspector({ store, state }) {
  const scope = state.selection.inspect;
  if (scope.kind === "agent") return html`<${Drawer} store=${store} state=${state} />`;
  const Panel = PANELS[scope.kind];
  const key = scopeKey(scope);
  const level = (to) => scope.level !== to && store.select({ inspect: switchPairLevel(state, scope), back: true });
  return html`<section class="drawer inspector">
    <header class="drawer-head">
      <${BackButton} store=${store} state=${state} />
      <div class="insp-title"><div class="drawer-name">${scopeLabel(state, scope)}</div>
        <div><${Chip} tone="info">${KIND_LABEL[scope.kind]}<//>
          ${scope.kind === "pair" ? html`<span class="seg">
            <button class=${scope.level === "agent" ? "on" : ""} onClick=${() => level("agent")}>Agents</button>
            <button class=${scope.level === "org" ? "on" : ""} onClick=${() => level("org")}>Organizations</button>
          </span>` : null}</div></div>
      <span class="spacer"></span>
      <button onClick=${() => store.select({ focus: scope.kind === "thread" ? scope.id : scope })}>Focus on map</button>
      <button aria-label="Close" onClick=${() => store.select({ inspect: null })}>×</button>
    </header>
    <div class="drawer-body">
      ${exists(state, scope)
        ? html`<${SummaryCard} key=${key} state=${state} scope=${scope} />
          <${Panel} key=${key} store=${store} state=${state} scope=${scope} />`
        : html`<p class="muted">Not in this run.</p>`}
    </div>
  </section>`;
}

// Shared by the three kinds: a tab bar kept in local state, and a list cap.
export function useTabs(tabs) {
  const [tab, setTab] = useState(tabs[0][0]);
  const bar = html`<nav class="tabs">${tabs.map(([k, label]) => html`<button class=${tab === k ? "on" : ""}
    onClick=${() => setTab(k)}>${label}</button>`)}</nav>`;
  return [tab, bar];
}

export function Capped({ rows, render, limit = 200 }) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(-limit);
  return html`<div>${shown.map(render)}
    ${!all && rows.length > limit ? html`<button class="link" onClick=${() => setAll(true)}>Show all ${rows.length}</button>` : null}</div>`;
}
