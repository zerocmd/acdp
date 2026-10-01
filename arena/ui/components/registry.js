import { html, useEffect, useState } from "../preact.js";
import { getJson } from "../api.js";
import { diffKeys } from "../lib/diff.js";
import { Checks } from "./steps.js";

function CardCompare({ entry }) {
  // undefined = loading, null = unavailable, object = loaded.
  const [stored, setStored] = useState(undefined);
  const [live, setLive] = useState(undefined);
  const slug = entry.id.split(".")[0];
  useEffect(() => {
    getJson(`/arena/registry/agents/${entry.id}/card`).then(setStored).catch(() => setStored(null));
    getJson(`/agents/${slug}/.well-known/agent-card.json`).then(setLive).catch(() => setLive(null));
  }, [entry.id]);
  let note;
  if (stored === undefined || live === undefined) note = html`<span class="muted">Loading cards…</span>`;
  else if (!stored || !live) note = html`<span class="muted">${!stored ? "Stored card" : "Live card"} unavailable, so no comparison.</span>`;
  else {
    const differ = diffKeys(stored, live);
    note = differ.length ? html`<span class="bad">Stored and live cards differ in: ${differ.join(", ")}</span>`
      : html`<span class="ok">Stored card matches the live card.</span>`;
  }
  return html`<div class="compare">
    <p>${note}</p>
    <div class="split2">
      <div><h5>Stored in registry</h5><pre>${stored ? JSON.stringify(stored, null, 2) : "—"}</pre></div>
      <div><h5>Live</h5><pre>${live ? JSON.stringify(live, null, 2) : "—"}</pre></div>
    </div>
  </div>`;
}

function Organizations({ orgs, entries }) {
  return html`<table class="grid">
    <tr><th>Organization</th><th>Canonical domain</th><th>Agents claiming it</th></tr>
    ${orgs.map((o) => {
      const claims = entries.filter((e) => e.organization === o.organization);
      return html`<tr><td>${o.organization}</td><td>${o.canonical_domain}</td>
        <td>${claims.map((e) => html`<div class=${e.domain === o.canonical_domain ? "" : "bad"}>${e.id}</div>`)}</td></tr>`;
    })}
  </table>`;
}

export function RegistryView({ store }) {
  const [entries, setEntries] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [orgsError, setOrgsError] = useState("");
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [open, setOpen] = useState(null);
  const [tab, setTab] = useState("entries");
  const load = () => {
    setError("");
    getJson("/arena/registry").then((d) => setEntries(d.agents || [])).catch((e) => setError(e.message));
    setOrgsError("");
    getJson("/arena/registry/orgs").then((d) => setOrgs(d.orgs || [])).catch((e) => setOrgsError(e.message));
  };
  useEffect(load, []);
  const q = query.toLowerCase();
  const shown = entries.filter((e) => {
    const s = (e.verification || {}).status || "unknown";
    if (status !== "all" && s !== status) return false;
    return !q || [e.name, e.organization, e.domain, ...(e.capabilities || [])].join(" ").toLowerCase().includes(q);
  });
  return html`<div class="view scroll registry">
    ${error ? html`<div class="banner">${error}</div>` : null}
    <div class="toolbar">
      <button class=${tab === "entries" ? "on" : ""} onClick=${() => setTab("entries")}>Entries</button>
      <button class=${tab === "orgs" ? "on" : ""} onClick=${() => setTab("orgs")}>Organizations</button>
      <input placeholder="search name, org, capability, domain" value=${query} onInput=${(e) => setQuery(e.target.value)} />
      <select value=${status} onChange=${(e) => setStatus(e.target.value)}>
        <option value="all">All</option><option value="verified">Verified</option><option value="failed">Failed</option></select>
      <button onClick=${load}>Refresh</button>
    </div>
    ${tab === "orgs" ? (orgsError ? html`<p class="error">Organization list unavailable: ${orgsError}</p>`
      : html`<${Organizations} orgs=${orgs} entries=${entries} />`) : html`<table class="grid">
      <tr><th>Agent</th><th>Organization</th><th>Capability</th><th>Status</th><th>Last update</th></tr>
      ${shown.map((e) => {
        const v = e.verification || {};
        return html`<tr class="row" onClick=${() => setOpen(open === e.id ? null : e.id)}>
            <td>${e.name}<div class="muted">${e.id}</div></td><td>${e.organization}</td>
            <td>${(e.capabilities || []).join(", ")}</td>
            <td class=${v.status === "verified" ? "ok" : v.status === "failed" ? "bad" : "muted"}>${v.status || "unknown"}</td>
            <td>${e.last_update ? new Date(e.last_update * 1000).toLocaleTimeString() : "—"}</td>
          </tr>
          ${open === e.id ? html`<tr><td colspan="5">
            <button class="link" onClick=${() => store.select({ agent: e.id, tab: "overview" })}>Open agent</button>
            <h5>Verification</h5><${Checks} verification=${v} />
            <h5>Stored entry</h5><pre>${JSON.stringify(e, null, 2)}</pre>
            <${CardCompare} entry=${e} />
          </td></tr>` : null}`;
      })}
    </table>`}
  </div>`;
}
