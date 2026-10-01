// Colors shared by every view. Pure: Node tests import it.
export const COMPANY_COLORS = ["#3b5bdb", "#0ca678", "#f08c00", "#7048e8", "#1098ad",
  "#e8590c", "#5c940d", "#c2255c", "#495057", "#1c7ed6"];
export const THREAD_COLORS = ["#3b5bdb", "#0ca678", "#f08c00", "#7048e8", "#1098ad",
  "#e8590c", "#5c940d", "#c2255c", "#495057", "#1c7ed6", "#9c36b5", "#2b8a3e"];
// CSS custom properties defined in style.css (light and dark).
export const TRUST_TOKENS = { verified: "--ok", pending: "--pending", failed: "--bad", unknown: "--muted" };

export function companyColor(domain) {
  let hash = 0;
  for (const ch of domain || "") hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return COMPANY_COLORS[hash % COMPANY_COLORS.length];
}

export function threadColor(index) {
  return THREAD_COLORS[(index ?? 0) % THREAD_COLORS.length];
}
