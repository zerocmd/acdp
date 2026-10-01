// Workbench event store. Pure: no DOM, no network, no CDN imports.
// The WebSocket feeds events into apply(); components read the state.

export const HANDLED = [
  "bus.reset", "arena.started", "arena.idle", "arena.paused", "arena.resumed", "arena.stopped",
  "agent.registered", "agent.verified", "agent.verification_failed", "agent.error",
  "registration.step", "discovery.query", "decision.made", "decision.rejected",
  "thread.opened", "thread.closed", "message.sent", "message.failed",
  "verification.peer_check", "task.created", "task.updated",
];

const MAX_MESSAGES = 2000;
const MAX_TIMELINE = 4000;
const KEEP = 20;
const LANE = {
  "agent.registered": "register", "registration.step": "register",
  "discovery.query": "discover",
  "verification.peer_check": "verify", "agent.verified": "verify",
  "agent.verification_failed": "verify",
  "message.sent": "message", "message.failed": "message",
  "task.created": "message", "task.updated": "message",
};

function initialSelection() {
  return { agent: null, thread: "t1", allThreads: false, range: null, view: "network",
    tab: "overview", adding: false, allQueries: false, pair: null };
}

export function initialState() {
  return {
    mode: "connecting", runId: "", log: "", stopReason: "", paused: false, generation: 0,
    lastSeq: -1, unknown: 0,
    agents: {}, order: [], threads: {}, threadOrder: [], messages: [],
    trustByMessage: {}, tasks: {}, taskByMessage: {}, timeline: [],
    highlight: null, lastQuery: null, selection: initialSelection(),
  };
}

function agentRecord(id) {
  return {
    id, slug: id.split(".")[0], name: id, organization: "", domain: id.split(".").slice(1).join("."),
    capability: "", needs: [], model: "", role: "", cadence: null, did: "", systemPrompt: "",
    status: "pending", reasons: [], steps: {}, trust: {}, queries: [], decisions: [],
    counters: { sent: 0, received: 0, rejected: 0, errors: 0 }, lastPrompt: "", lastDecision: null,
  };
}

function ensureAgent(state, id) {
  if (!state.agents[id]) {
    state.agents[id] = agentRecord(id);
    state.order.push(id);
  }
  return state.agents[id];
}

function keepLast(list, item, size = KEEP) {
  list.push(item);
  if (list.length > size) list.splice(0, list.length - size);
}

function system(state, event, text, threadId = null) {
  keepLast(state.messages, { kind: "system", id: `s${event.seq}`, seq: event.seq, ts: event.ts, threadId, text }, MAX_MESSAGES);
}

function laneAgent(type, d) {
  if (type === "verification.peer_check" || type === "discovery.query") return d.agent;
  if (type === "message.sent") return d.from_id;
  if (type === "message.failed") return d.from_id;
  if (type === "task.created") return d.requester;
  return d.id || d.agent || null;
}

function laneLabel(type, d) {
  switch (type) {
    case "registration.step": return `${d.id}: ${d.step} ${d.status}`;
    case "agent.registered": return `${d.name} joined`;
    case "discovery.query": return `${d.agent} searched ${d.capability}`;
    case "verification.peer_check": return `${d.agent} checked ${d.sender}: ${d.status}${d.reason ? ` (${d.reason})` : ""}`;
    case "message.sent": return `${d.from_id} → ${d.to_id} (${d.intent})`;
    case "task.created": return `task ${d.task_id} working`;
    case "task.updated": return `task ${d.task_id} ${d.state}`;
    default: return type;
  }
}

function laneFailed(type, d) {
  return d.status === "failed" || type === "agent.verification_failed" || type === "message.failed"
    || (type === "message.sent" && (d.intent === "decline" || d.intent === "challenge"));
}

function normalizeResult(r) {
  if (typeof r === "string") return { id: r, name: r, organization: "", domain: "", status: "unknown", new: false };
  return { id: r.id, name: r.name || r.id, organization: r.organization || "", domain: r.domain || "",
    status: r.status || "unknown", new: Boolean(r.new) };
}

export function apply(state, event) {
  const { type, seq, ts } = event;
  const d = event.data || {};
  if (type === "bus.reset") {
    const next = initialState();
    next.mode = "replay";
    next.log = d.log || "";
    next.lastSeq = seq;
    // Views that keep their own state (Network) remount when this changes.
    next.generation = state.generation + 1;
    next.selection = { ...initialSelection(), view: state.selection.view };
    return next;
  }
  if (typeof seq === "number") {
    if (seq <= state.lastSeq) return state;
    state.lastSeq = seq;
  }
  if (!HANDLED.includes(type)) {
    state.unknown += 1;
    return state;
  }
  if (LANE[type]) {
    keepLast(state.timeline, { seq, ts, lane: LANE[type], type, agent: laneAgent(type, d),
      label: laneLabel(type, d), failed: laneFailed(type, d) }, MAX_TIMELINE);
  }
  const replay = state.mode === "replay";
  switch (type) {
    case "arena.started":
      if (!replay) state.mode = "live";
      state.runId = d.run_id || state.runId;
      break;
    case "arena.idle":
      if (!replay) state.mode = "idle";
      system(state, event, `Arena idle: ${d.reason}`);
      break;
    case "arena.paused": state.paused = true; break;
    case "arena.resumed": state.paused = false; break;
    case "arena.stopped":
      state.stopReason = d.reason || "";
      if (!replay) state.mode = "stopped";
      system(state, event, `Arena stopped: ${d.reason}`);
      break;
    case "agent.registered": {
      const a = ensureAgent(state, d.id);
      Object.assign(a, {
        slug: d.slug || a.slug, name: d.name || a.name, organization: d.organization || "",
        domain: d.domain || a.domain, capability: d.capability || "", needs: d.needs || [],
        model: d.model || "", role: d.role || "", cadence: d.cadence || null, did: d.did || "",
        systemPrompt: d.system_prompt || a.systemPrompt,
      });
      system(state, event, `${a.name} (${a.organization}, ${a.domain}) joined`);
      break;
    }
    case "registration.step": {
      const a = ensureAgent(state, d.id);
      a.steps[d.step] = { status: d.status, detail: d.detail || {}, ts };
      if (d.step === "result") {
        a.status = (d.detail || {}).status === "verified" ? "verified" : "failed";
        a.reasons = (d.detail || {}).reasons || [];
      }
      break;
    }
    case "agent.verified":
      ensureAgent(state, d.id).status = "verified";
      system(state, event, `${state.agents[d.id].name} verified by the registry`);
      break;
    case "agent.verification_failed": {
      const a = ensureAgent(state, d.id);
      a.status = "failed";
      a.reasons = d.reasons || [];
      system(state, event, `${a.name} failed verification: ${a.reasons.join("; ")}`);
      break;
    }
    case "agent.error":
      ensureAgent(state, d.id).counters.errors += 1;
      system(state, event, `${d.id} error: ${d.error}`);
      break;
    case "discovery.query": {
      const a = ensureAgent(state, d.agent);
      const query = { seq, ts, agent: d.agent, capability: d.capability, results: (d.results || []).map(normalizeResult) };
      keepLast(a.queries, query);
      state.lastQuery = query;
      if (query.results.some((r) => r.new)) state.highlight = query;
      break;
    }
    case "decision.made": {
      const a = ensureAgent(state, d.agent);
      keepLast(a.decisions, { ...d, seq, ts });
      if ((d.outcome || "").startsWith("rejected")) a.counters.rejected += 1;
      a.lastPrompt = d.prompt || "";
      a.lastDecision = d.decision || null;
      break;
    }
    case "decision.rejected": break;
    case "thread.opened":
      state.threads[d.id] = { id: d.id, owner: d.owner, title: d.title, color: d.color,
        closed: false, reason: "", count: 0, unread: 0 };
      state.threadOrder.push(d.id);
      system(state, event, `Thread ${d.id} opened: ${d.title}`, d.id);
      break;
    case "thread.closed":
      if (state.threads[d.id]) Object.assign(state.threads[d.id], { closed: true, reason: d.reason });
      system(state, event, `Thread ${d.id} closed (${d.reason})`, d.id);
      break;
    case "verification.peer_check": {
      const trust = { status: d.status, reason: d.reason || "" };
      state.trustByMessage[d.message_id] = trust;
      ensureAgent(state, d.agent).trust[d.sender] = trust;
      const known = state.messages.find((m) => m.id === d.message_id);
      if (known) known.trust = trust;
      break;
    }
    case "message.sent": {
      const earlier = [...state.messages].reverse().find((m) => m.kind === "message"
        && m.threadId === d.thread_id && m.from === d.to_id && m.to === d.from_id);
      const message = {
        kind: "message", id: d.id, seq, ts, threadId: d.thread_id,
        from: d.from_id, to: d.to_id, intent: d.intent, body: d.body, color: d.color,
        lookingFor: d.looking_for || "", whyThisPeer: d.why_this_peer || "",
        trust: state.trustByMessage[d.id] || null, replyTo: earlier ? earlier.id : null,
      };
      keepLast(state.messages, message, MAX_MESSAGES);
      const thread = state.threads[d.thread_id];
      if (thread) {
        thread.count += 1;
        const visible = state.selection.allThreads || state.selection.thread === d.thread_id;
        if (!visible) thread.unread += 1;
      }
      ensureAgent(state, d.from_id).counters.sent += 1;
      ensureAgent(state, d.to_id).counters.received += 1;
      break;
    }
    case "message.failed":
      system(state, event, `Message ${d.from_id} → ${d.to_id} failed: ${d.error}`);
      break;
    case "task.created":
      state.tasks[d.task_id] = { id: d.task_id, requester: d.requester, recipient: d.recipient,
        messageId: d.message_id, threadId: d.thread_id, state: "working", artifact: "", reason: "",
        replyId: "" };
      state.taskByMessage[d.message_id] = d.task_id;
      break;
    case "task.updated":
      if (state.tasks[d.task_id]) Object.assign(state.tasks[d.task_id], {
        state: d.state, artifact: d.artifact || "", reason: d.reason || "", replyId: d.reply_id || "" });
      break;
    default: break;
  }
  return state;
}

export function select(state, patch) {
  state.selection = { ...state.selection, ...patch };
  if (patch.pair === undefined && ("agent" in patch || "thread" in patch || "allThreads" in patch)) {
    state.selection.pair = null;
  }
  if (patch.thread && state.threads[patch.thread]) state.threads[patch.thread].unread = 0;
  if (patch.allThreads) for (const t of Object.values(state.threads)) t.unread = 0;
  return state;
}

export function chatItems(state) {
  const { thread, allThreads, agent, range, pair } = state.selection;
  return state.messages.filter((m) => {
    if (range && (m.ts < range[0] || m.ts > range[1])) return false;
    if (pair) return m.kind === "message" && m.from === pair[0] && m.to === pair[1];
    if (agent) return m.kind === "message" && (m.from === agent || m.to === agent);
    if (allThreads) return true;
    return m.threadId === thread || (m.kind === "system" && m.threadId === null);
  });
}

export function agentsByCompany(state) {
  const groups = new Map();
  for (const id of state.order) {
    const a = state.agents[id];
    if (!groups.has(a.domain)) groups.set(a.domain, { domain: a.domain, organization: a.organization, agents: [] });
    groups.get(a.domain).agents.push(a);
  }
  return [...groups.values()];
}

// Live-only data (live card, pending inbox, agent state) comes from running
// agents. A replay shows a past run, so the current agents do not match it.
export function liveDataAvailable(mode) {
  return mode === "live" || mode === "stopped";
}

export function createStore() {
  let state = initialState();
  const subscribers = new Set();
  const notify = () => subscribers.forEach((fn) => fn());
  return {
    get: () => state,
    dispatch(event) { state = apply(state, event); notify(); },
    reset() {
      const view = state.selection.view;
      const generation = state.generation + 1;
      state = initialState();
      state.generation = generation;
      state.selection.view = view;
      notify();
    },
    select(patch) { state = select(state, patch); notify(); },
    setMode(mode) { state.mode = mode; notify(); },
    subscribe(fn) { subscribers.add(fn); return () => subscribers.delete(fn); },
  };
}
