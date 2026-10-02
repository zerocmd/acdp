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

// An agent name, with the domain when another agent uses the same name.
export function agentLabel(state, id) {
  const a = state.agents[id];
  if (!a) return id;
  const shared = Object.values(state.agents).some((b) => b.name === a.name && b.id !== id);
  return shared ? `${a.name} (${a.domain})` : a.name;
}
const agentName = agentLabel;
export const orgName = (state, domain) =>
  Object.values(state.agents).find((a) => a.domain === domain)?.organization || domain;

// An organization name, with the domain when another domain uses the same name
// (an impostor copies the real organization's name).
export function orgLabel(state, domain) {
  const name = orgName(state, domain);
  const shared = Object.values(state.agents).some((a) => a.organization === name && a.domain !== domain);
  return shared ? `${name} (${domain})` : name;
}

export function scopeLabel(state, scope) {
  const s = normScope(scope);
  if (!s) return "";
  if (s.kind === "thread") return `${s.id} ${state.threads[s.id]?.title || ""}`.trim();
  if (s.kind === "agent") return agentName(state, s.id);
  if (s.kind === "org") return orgLabel(state, s.domain);
  const name = (x) => (s.level === "org" ? orgLabel(state, x) : agentName(state, x));
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
const inRange = (state, ts) => {
  const range = state.selection.range;
  return !range || ts == null || (ts >= range[0] && ts <= range[1]);
};

export function orgStats(state, domain) {
  const agents = Object.values(state.agents).filter((a) => a.domain === domain);
  const ids = new Set(agents.map((a) => a.id));
  const ms = scopeMessages(state, { kind: "org", domain });
  const tasks = { completed: 0, working: 0, rejected: 0 };
  for (const t of Object.values(state.tasks)) {
    if ((!ids.has(t.requester) && !ids.has(t.recipient)) || !inRange(state, t.created)) continue;
    if (t.state === "completed") tasks.completed += 1;
    else if (t.state === "working") tasks.working += 1;
    else tasks.rejected += 1;
  }
  return {
    agents,
    organization: agents[0]?.organization || domain,
    sector: agents[0]?.sector || "provider",
    failed: agents.length > 0 && agents.every((a) => a.status === "failed"),
    out: ms.filter((m) => ids.has(m.from)).length,
    in: ms.filter((m) => ids.has(m.to)).length,
    threadsOpened: state.threadOrder.filter((id) => ids.has(state.threads[id].owner)
      && inRange(state, state.threads[id].opened)).length,
    tasks,
  };
}

export function partnerRows(state, domain) {
  const rows = new Map();
  const dom = (id) => domainOf(state.agents, id);
  for (const m of scopeMessages(state, { kind: "org", domain })) {
    const outgoing = dom(m.from) === domain;
    const partner = outgoing ? dom(m.to) : dom(m.from);
    if (!rows.has(partner)) {
      rows.set(partner, { domain: partner, organization: orgName(state, partner), out: 0, in: 0,
        threads: new Set(), last: 0, declines: 0, trustFailures: 0 });
    }
    const r = rows.get(partner);
    if (outgoing) r.out += 1;
    if (dom(m.to) === domain) r.in += 1;
    r.threads.add(m.threadId);
    r.last = Math.max(r.last, m.ts);
    if (isDecline(m)) r.declines += 1;
    if (trustFailed(m)) r.trustFailures += 1;
  }
  return [...rows.values()].map((r) => ({ ...r, threads: r.threads.size }))
    .sort((x, y) => (y.out + y.in) - (x.out + x.in) || x.domain.localeCompare(y.domain));
}

export function orgTrust(state, domain) {
  const all = Object.values(state.agents);
  const mine = new Set(all.filter((a) => a.domain === domain).map((a) => a.id));
  const against = [];
  const by = [];
  for (const a of all) {
    for (const [sender, t] of Object.entries(a.trust)) {
      if (t.status === "verified") continue;
      if (mine.has(sender) && !mine.has(a.id)) against.push({ checker: a.id, sender, reason: t.reason });
      if (mine.has(a.id)) by.push({ checker: a.id, sender, reason: t.reason });
    }
  }
  const pins = all.filter((a) => mine.has(a.id)).map((a) => ({ id: a.id, status: a.status,
    dns: a.steps.dns?.status || "—", checks: a.steps.checks?.status || "—", reasons: a.reasons }));
  return { against, by, pins };
}

function threadRow(state, id) {
  const t = state.threads[id];
  const ms = state.messages.filter((m) => m.kind === "message" && m.threadId === id);
  const participants = new Set([t.owner]);
  for (const m of ms) { participants.add(m.from); participants.add(m.to); }
  const verdict = ms.some((m) => m.intent === "verdict");
  const end = t.closed ? (t.closedAt ?? ms[ms.length - 1]?.ts) : ms[ms.length - 1]?.ts;
  return {
    id, title: t.title, owner: t.owner, participants: [...participants], count: ms.length,
    status: t.closed ? (verdict ? "verdict" : "closed") : "open",
    duration: t.opened != null && end != null ? Math.max(0, Math.round(end - t.opened)) : null,
  };
}

export function scopeThreads(state, scope) {
  const s = normScope(scope);
  const ids = new Set(scopeMessages(state, s).map((m) => m.threadId));
  if (s.kind === "org") {
    for (const id of state.threadOrder) {
      if (domainOf(state.agents, state.threads[id].owner) === s.domain) ids.add(id);
    }
  }
  return state.threadOrder.filter((id) => ids.has(id)).map((id) => threadRow(state, id));
}

export function pairStats(state, scope) {
  const side = (id) => (scope.level === "org" ? domainOf(state.agents, id) : id);
  const matches = (x, y) => { const [lo, hi] = sortPair(x, y); return lo === scope.a && hi === scope.b && x !== y; };
  const messages = scopeMessages(state, scope);
  const responses = [];
  messages.forEach((m, i) => {
    if (m.intent !== "request") return;
    const back = messages.slice(i + 1).find((r) => r.threadId === m.threadId
      && side(r.from) === side(m.to) && side(r.to) === side(m.from));
    if (back) responses.push({ id: m.id, seconds: Math.round(back.ts - m.ts) });
  });
  const secs = responses.map((r) => r.seconds).sort((x, y) => x - y);
  const checks = [];
  const finds = [];
  for (const a of Object.values(state.agents)) {
    for (const [sender, t] of Object.entries(a.trust)) {
      if (matches(side(a.id), side(sender))) checks.push({ checker: a.id, sender, status: t.status, reason: t.reason });
    }
    for (const q of a.queries) {
      if (!inRange(state, q.ts)) continue;
      for (const r of q.results) {
        if (matches(side(a.id), side(r.id))) finds.push({ agent: a.id, found: r.id, capability: q.capability, ts: q.ts, new: r.new });
      }
    }
  }
  return {
    messages,
    threads: [...new Set(messages.map((m) => m.threadId))],
    responses,
    median: secs.length ? secs[Math.floor((secs.length - 1) / 2)] : null,
    slowest: secs.length ? secs[secs.length - 1] : null,
    declines: messages.filter(isDecline).length,
    trustFailures: messages.filter(trustFailed).length,
    tasks: Object.values(state.tasks).filter((t) => inRange(state, t.created)
      && inScope(scope, { from: t.requester, to: t.recipient, threadId: t.threadId }, state.agents)),
    checks,
    finds,
  };
}

export function threadStory(state, id) {
  const t = state.threads[id];
  if (!t) return [];
  const ms = state.messages.filter((m) => m.kind === "message" && m.threadId === id);
  const start = t.opened ?? ms[0]?.ts ?? 0;
  const end = t.closedAt ?? Infinity;
  const steps = [{ kind: "opened", ts: start, agent: t.owner, text: t.title }];
  // For each sender's first message to a recipient, show the latest search before it
  // that found the recipient: how the sender found that peer.
  const firstContact = new Map();
  for (const m of ms) if (!firstContact.has(`${m.from}>${m.to}`)) firstContact.set(`${m.from}>${m.to}`, m);
  const shown = new Set();
  for (const m of firstContact.values()) {
    const q = [...(state.agents[m.from]?.queries || [])].reverse()
      .find((x) => x.ts >= start && x.ts <= m.ts && x.ts <= end && x.results.some((r) => r.id === m.to));
    if (!q || shown.has(q.seq)) continue;
    shown.add(q.seq);
    const found = q.results.filter((r) => firstContact.has(`${m.from}>${r.id}`));
    steps.push({ kind: "search", ts: q.ts, agent: m.from,
      text: `searched ${q.capability}: found ${found.map((r) => agentName(state, r.id)).join(", ")}` });
  }
  for (const m of ms) {
    steps.push({ kind: "message", ts: m.ts, agent: m.from, to: m.to, intent: m.intent, id: m.id,
      text: m.body.slice(0, 160), lookingFor: m.lookingFor, whyThisPeer: m.whyThisPeer, failed: trustFailed(m) });
  }
  if (t.closed) {
    const verdict = [...ms].reverse().find((m) => m.intent === "verdict");
    steps.push({ kind: "closed", ts: t.closedAt ?? ms[ms.length - 1]?.ts ?? start, agent: verdict?.from || t.owner,
      text: verdict ? verdict.body.slice(0, 160) : `closed (${t.reason || "no reason"})` });
  }
  const order = { opened: 0, search: 1, message: 1, closed: 2 };
  return steps.map((x, i) => ({ ...x, i }))
    .sort((x, y) => order[x.kind] - order[y.kind] || x.ts - y.ts || x.i - y.i)
    .map(({ i, ...x }) => x);
}

export function threadParticipants(state, id) {
  const t = state.threads[id];
  if (!t) return [];
  const rows = new Map();
  const add = (aid, by) => { if (!rows.has(aid)) rows.set(aid, { id: aid, broughtBy: by, sent: 0, received: 0 }); };
  add(t.owner, null);
  for (const m of state.messages) {
    if (m.kind !== "message" || m.threadId !== id) continue;
    add(m.from, null);
    add(m.to, m.from);
    rows.get(m.from).sent += 1;
    rows.get(m.to).received += 1;
  }
  return [...rows.values()];
}
