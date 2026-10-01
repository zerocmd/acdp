import { html } from "../preact.js";

export const STEP_LABELS = [
  ["identity", "Identity minted"], ["zone", "Zone ready"], ["dns", "DNS published"],
  ["card", "Agent Card served"], ["submitted", "Submitted to registry"],
  ["checks", "Registry checks"], ["result", "Result"],
];

const mark = (ok) => (ok ? "✓" : "✕");

export function Checks({ verification }) {
  if (!verification) return null;
  const v = verification;
  const rows = [
    ["card re-fetched", v.card_fetched], ["TXT record found", v.dns_found],
    ["key matches DNS", v.key_matches_dns],
    ["organization anchor", v.org_conflict === undefined ? undefined : !v.org_conflict],
  ];
  return html`<ul class="checks">
    ${rows.filter(([, ok]) => ok !== undefined).map(([label, ok]) =>
      html`<li class=${ok ? "ok" : "bad"}>${mark(ok)} ${label}</li>`)}
    ${v.canonical_domain ? html`<li class="muted">canonical domain: ${v.canonical_domain}</li>` : null}
    ${(v.reasons || []).map((r) => html`<li class="bad">${r}</li>`)}
    ${v.checked_at ? html`<li class="muted">checked ${v.checked_at}</li>` : null}
  </ul>`;
}

function detail(step, d) {
  switch (step) {
    case "identity": return html`<div><code>${d.did}</code><div class="muted">fingerprint <code>${d.fingerprint}</code></div></div>`;
    case "zone": return html`<code>${d.zone}</code> <span class="muted">(${d.result})</span>`;
    case "dns": return d.skipped ? html`<span class="muted">skipped (no TXT record)</span>`
      : d.error ? html`<span class="bad">${d.error}</span>`
      : html`<div>SRV <code>${d.srv}</code><div>TXT ${(d.txt || []).map((t) => html`<code class="txt">${t}</code>`)}</div></div>`;
    case "card": return html`<a href=${new URL(d.card_url).pathname} target="_blank">${new URL(d.card_url).pathname}</a>`;
    case "checks": return html`<${Checks} verification=${d} />`;
    case "result": return html`<span class=${d.status === "verified" ? "ok" : "bad"}>${d.status}</span>
      ${(d.reasons || []).length ? html` — ${d.reasons.join("; ")}` : null}`;
    default: return d.error ? html`<span class="bad">${d.error}</span>` : null;
  }
}

export function Stepper({ agent }) {
  return html`<ol class="stepper">
    ${STEP_LABELS.map(([step, label]) => {
      const s = agent.steps[step];
      const cls = !s ? "pending" : s.status === "ok" ? "ok" : s.status === "skipped" ? "skipped" : "bad";
      return html`<li class=${cls}><strong>${label}</strong>${s ? html`<div>${detail(step, s.detail)}</div>` : html`<div class="muted">—</div>`}</li>`;
    })}
  </ol>`;
}
