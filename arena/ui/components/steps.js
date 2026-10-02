// Registration steps as a compact chip row; click a step to see its detail.
import { html, useState } from "../preact.js";
import { Chip, CodeBox } from "./cards.js";

export const STEP_LABELS = [
  ["identity", "Identity"], ["zone", "Zone"], ["dns", "DNS"], ["card", "Card"],
  ["submitted", "Submitted"], ["checks", "Checks"], ["result", "Result"],
];

export function Checks({ verification }) {
  if (!verification) return null;
  const v = verification;
  const rows = [["card re-fetched", v.card_fetched], ["TXT found", v.dns_found],
    ["key matches DNS", v.key_matches_dns], ["org anchor", v.org_conflict === undefined ? undefined : !v.org_conflict]];
  const shown = rows.filter(([, ok]) => ok !== undefined);
  return html`<div>
    ${!shown.length && v.status ? html`<${Chip} tone=${v.status === "verified" ? "ok" : "bad"}>${v.status}<//>` : null}
    ${shown.map(([label, ok]) => html`<${Chip} tone=${ok ? "ok" : "bad"}>${ok ? "✓" : "✕"} ${label}<//>`)}
    ${(v.reasons || []).map((r) => html`<${Chip} tone="bad">${r}<//>`)}
    ${v.canonical_domain ? html`<div class="muted small">canonical domain ${v.canonical_domain}${v.checked_at ? ` · checked ${v.checked_at.slice(11, 19)} UTC` : ""}</div>` : null}
  </div>`;
}

function Detail({ step, d }) {
  if (d.error) return html`<${Chip} tone="bad">${d.error}<//>`;
  switch (step) {
    case "identity": return html`<div class="muted small">DID</div><${CodeBox} text=${d.did} />
      <div class="muted small">Key fingerprint</div><${CodeBox} text=${d.fingerprint} />`;
    case "zone": return html`<div><code>${d.zone}</code> <${Chip}>${d.result}<//></div>`;
    case "dns": return d.skipped ? html`<${Chip} tone="pending">skipped: no TXT record<//>` : html`<div>
      <${CodeBox} text=${`SRV ${d.srv}`} />
      <table class="kv">${(d.txt || []).map((t) => { const [k, ...rest] = t.split("="); return html`<tr><td>${k}</td><td>${rest.join("=")}</td></tr>`; })}</table></div>`;
    case "card": return html`<a href=${new URL(d.card_url, location.href).pathname} target="_blank">${new URL(d.card_url, location.href).pathname}</a>`;
    case "checks": return html`<${Checks} verification=${d} />`;
    case "result": return html`<${Chip} tone=${d.status === "verified" ? "ok" : "bad"}>${d.status}<//>
      ${(d.reasons || []).map((r) => html`<${Chip} tone="bad">${r}<//>`)}`;
    default: return null;
  }
}

export function StepChips({ agent }) {
  const [open, setOpen] = useState(null);
  return html`<div>
    <div class="steps-row">
      ${STEP_LABELS.map(([step, label], i) => {
        const s = agent.steps[step];
        const tone = !s ? "neutral" : s.status === "ok" ? "ok" : s.status === "skipped" ? "pending" : "bad";
        return html`<button class=${`step-chip${open === step ? " open" : ""}`} style=${`--tone:var(--${tone === "neutral" ? "line" : tone === "pending" ? "pending" : tone})`}
          disabled=${!s} onClick=${() => setOpen(open === step ? null : step)}>${i + 1} ${label}</button>`;
      })}
    </div>
    ${open && agent.steps[open] ? html`<div class="step-detail"><${Detail} step=${open} d=${agent.steps[open].detail} /></div>` : null}
  </div>`;
}
