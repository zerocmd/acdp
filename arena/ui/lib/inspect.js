// Inspector data: scopes, filters, and the free summary. Pure: Node tests import it.
// A scope is {kind: "agent", id} | {kind: "org", domain} | {kind: "thread", id}
// | {kind: "pair", a, b, level: "agent" | "org"} with a <= b.

export const UNANSWERED_S = 120;
const MAX_REQUEST_MESSAGES = 80;
const MAX_REQUEST_BODY = 600;

export const sortPair = (a, b) => (a <= b ? [a, b] : [b, a]);

export function pairScope(a, b, level = "agent") {
  const [lo, hi] = sortPair(a, b);
  return { kind: "pair", a: lo, b: hi, level };
}

export function normScope(focus) {
  if (!focus) return null;
  return typeof focus === "string" ? { kind: "thread", id: focus } : focus;
}

export function scopeKey(scope) {
  const s = normScope(scope);
  if (!s) return "";
  if (s.kind === "pair") return `pair:${s.level}:${s.a}|${s.b}`;
  return `${s.kind}:${s.kind === "org" ? s.domain : s.id}`;
}

export function domainOf(agents, id) {
  return agents[id]?.domain ?? String(id).split(".").slice(1).join(".");
}

export function inScope(scope, m, agents) {
  const s = normScope(scope);
  if (!s) return true;
  switch (s.kind) {
    case "thread": return m.threadId === s.id;
    case "agent": return m.from === s.id || m.to === s.id;
    case "org": return domainOf(agents, m.from) === s.domain || domainOf(agents, m.to) === s.domain;
    case "pair": {
      const side = (id) => (s.level === "org" ? domainOf(agents, id) : id);
      const [lo, hi] = sortPair(side(m.from), side(m.to));
      return lo === s.a && hi === s.b;
    }
    default: return false;
  }
}

export function scopeMessages(state, scope) {
  const range = state.selection.range;
  return state.messages.filter((m) => m.kind === "message"
    && (!range || (m.ts >= range[0] && m.ts <= range[1])) && inScope(scope, m, state.agents));
}

export function scopeAgents(state, scope) {
  const s = normScope(scope);
  const ids = new Set();
  if (!s) return ids;
  for (const m of scopeMessages(state, s)) { ids.add(m.from); ids.add(m.to); }
  if (s.kind === "thread" && state.threads[s.id]) ids.add(state.threads[s.id].owner);
  if (s.kind === "org") for (const a of Object.values(state.agents)) if (a.domain === s.domain) ids.add(a.id);
  if (s.kind === "pair" && s.level === "agent") { ids.add(s.a); ids.add(s.b); }
  if (s.kind === "agent") ids.add(s.id);
  return ids;
}

const agentName = (state, id) => state.agents[id]?.name || id;
export const orgName = (state, domain) =>
  Object.values(state.agents).find((a) => a.domain === domain)?.organization || domain;

export function scopeLabel(state, scope) {
  const s = normScope(scope);
  if (!s) return "";
  if (s.kind === "thread") return `${s.id} ${state.threads[s.id]?.title || ""}`.trim();
  if (s.kind === "agent") return agentName(state, s.id);
  if (s.kind === "org") return orgName(state, s.domain);
  const name = (x) => (s.level === "org" ? orgName(state, x) : agentName(state, x));
  return `${name(s.a)} ↔ ${name(s.b)}`;
}

export function switchPairLevel(state, scope) {
  if (scope.level === "agent") {
    return pairScope(domainOf(state.agents, scope.a), domainOf(state.agents, scope.b), "org");
  }
  const counts = new Map();
  for (const m of scopeMessages(state, scope)) {
    const key = sortPair(m.from, m.to).join("|");
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const busiest = [...counts.entries()].sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]))[0];
  if (!busiest) return scope;
  const [a, b] = busiest[0].split("|");
  return pairScope(a, b, "agent");
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const isDecline = (m) => m.intent === "decline" || m.intent === "challenge";
const trustFailed = (m) => Boolean(m.trust && m.trust.status !== "verified");

function firstAnswer(ms, m) {
  return ms.find((r) => r.ts >= m.ts && r !== m && r.threadId === m.threadId && r.from === m.to && r.to === m.from);
}

export function summarize(state, scope) {
  const s = normScope(scope);
  const ms = scopeMessages(state, s);
  const threads = [...new Set(ms.map((m) => m.threadId))];
  const label = scopeLabel(state, s);
  const head = [`${label}: ${plural(ms.length, "message")} in ${plural(threads.length, "thread")}`];
  const request = ms.find((m) => m.intent === "request");
  const answer = request && firstAnswer(ms, request);
  if (answer) head.push(`request answered in ${Math.round(answer.ts - request.ts)} s`);
  const verdict = [...ms].reverse().find((m) => m.intent === "verdict");
  const decline = [...ms].reverse().find(isDecline);
  const open = threads.some((t) => state.threads[t] && !state.threads[t].closed);
  let outcome = "no messages";
  if (verdict) outcome = verdict.body.slice(0, 160);
  else if (decline) outcome = `declined: ${decline.body.slice(0, 120)}`;
  else if (ms.length) outcome = open ? "open" : "closed";
  if (ms.length) head.push(verdict ? "closed by verdict" : decline ? "declined" : outcome);
  const tasks = Object.values(state.tasks).filter((t) =>
    inScope(s, { from: t.requester, to: t.recipient, threadId: t.threadId }, state.agents));
  const flags = [];
  if (ms.some(trustFailed)) flags.push("trust-failure");
  if (tasks.some((t) => t.state === "rejected")) flags.push("task-rejected");
  if (tasks.some((t) => t.state === "canceled")) flags.push("task-canceled");
  if (ms.some((m) => state.agents[m.from]?.status === "failed" || state.agents[m.to]?.status === "failed")) {
    flags.push("impostor-contact");
  }
  const allMessages = state.messages.filter((m) => m.kind === "message");
  const waiting = ms.some((m) => m.intent === "request" && state.lastTs - m.ts >= UNANSWERED_S
    && !allMessages.some((r) => r.threadId === m.threadId && r.from === m.to && r.to === m.from
      && r.ts >= m.ts && r.ts - m.ts <= UNANSWERED_S));
  if (waiting) flags.push("unanswered");
  const last = ms[ms.length - 1];
  return {
    headline: head.join(" · "),
    opening: request ? { text: request.body.slice(0, 160), lookingFor: request.lookingFor } : null,
    latest: last ? { from: agentName(state, last.from), intent: last.intent, text: last.body.slice(0, 160) } : null,
    outcome,
    flags,
    count: ms.length,
    lastSeq: last ? last.seq : -1,
  };
}

export function summaryRequest(state, scope) {
  const s = normScope(scope);
  const free = summarize(state, s);
  const agent = (id) => state.agents[id] || { name: id, organization: "" };
  return {
    kind: s.kind,
    title: scopeLabel(state, s).slice(0, 200),
    messages: scopeMessages(state, s).slice(-MAX_REQUEST_MESSAGES).map((m) => ({
      from_name: agent(m.from).name, from_org: agent(m.from).organization, to_name: agent(m.to).name,
      intent: m.intent, body: m.body.slice(0, MAX_REQUEST_BODY), trust: m.trust?.status || "", ts: m.ts,
    })),
    facts: {
      headline: free.headline, opening: free.opening?.text || "", latest: free.latest?.text || "",
      outcome: free.outcome, flags: free.flags.join(", "),
    },
  };
}
