import { test } from "node:test";
import assert from "node:assert/strict";
import { apply, chatItems, createStore, HANDLED, initialState, liveDataAvailable, select } from "../store.js";

let seq = 0;
const ev = (type, data, ts = 1000 + seq) => ({ seq: seq++, ts, run_id: "r", type, data });
const agent = (id, extra = {}) => ev("agent.registered", {
  id, slug: id.split(".")[0], name: id.split(".")[0], organization: "Org " + id,
  domain: id.split(".").slice(1).join("."), capability: "cap", model: "sonnet",
  role: "investigation", did: "did", needs: [], system_prompt: "SP", ...extra,
});
const run = (events) => events.reduce((s, e) => apply(s, e), initialState());

test("registration steps are recorded and result sets status", () => {
  const s = run([
    agent("a.x.example"),
    ev("registration.step", { id: "a.x.example", step: "zone", status: "ok", detail: { zone: "x.example", result: "created" } }),
    ev("registration.step", { id: "a.x.example", step: "result", status: "failed", detail: { status: "failed", reasons: ["key mismatch"] } }),
  ]);
  const a = s.agents["a.x.example"];
  assert.equal(a.steps.zone.detail.result, "created");
  assert.equal(a.status, "failed");
  assert.deepEqual(a.reasons, ["key mismatch"]);
  assert.equal(a.systemPrompt, "SP");
  assert.equal(s.timeline.filter((t) => t.lane === "register").length, 3);
});

test("old-format discovery results are accepted", () => {
  const s = run([agent("a.x.example"), ev("discovery.query", { agent: "a.x.example", capability: "cap", results: ["b.y.example"] })]);
  const q = s.agents["a.x.example"].queries[0];
  assert.deepEqual(q.results, [{ id: "b.y.example", name: "b.y.example", organization: "", domain: "", status: "unknown", new: false }]);
  assert.equal(s.highlight, null);
  assert.equal(s.lastQuery.capability, "cap");
});

test("new discovery results set the highlight", () => {
  const s = run([agent("a.x.example"), ev("discovery.query", { agent: "a.x.example", capability: "cap",
    results: [{ id: "b.y.example", name: "B", organization: "Y", domain: "y.example", status: "verified", new: true }] })]);
  assert.equal(s.highlight.agent, "a.x.example");
});

test("duplicate seq is ignored", () => {
  const msg = ev("message.sent", { id: "m1", thread_id: "t1", from_id: "a", to_id: "b", intent: "request", body: "hi", color: 0 });
  const s = run([msg, msg]);
  assert.equal(s.messages.filter((m) => m.kind === "message").length, 1);
});

test("bus.reset enters replay mode and replayed lifecycle events keep it", () => {
  const s = run([ev("bus.reset", { run_id: "replay-x", log: "x" }), ev("arena.started", { agents: 1 }), ev("arena.stopped", { reason: "done" })]);
  assert.equal(s.mode, "replay");
  assert.equal(s.log, "x");
});

test("live lifecycle events set mode", () => {
  let s = run([ev("arena.started", { agents: 1, run_id: "r1" })]);
  assert.equal(s.mode, "live");
  s = apply(s, ev("arena.stopped", { reason: "time limit reached" }));
  assert.equal(s.mode, "stopped");
  assert.equal(s.stopReason, "time limit reached");
});

test("messages get trust from the earlier peer check and reply links", () => {
  const s = run([
    ev("thread.opened", { id: "t1", owner: "a", title: "case", color: 0 }),
    ev("verification.peer_check", { agent: "b", sender: "a", message_id: "m1", status: "verified", reason: "" }),
    ev("message.sent", { id: "m1", thread_id: "t1", from_id: "a", to_id: "b", intent: "request", body: "q", color: 0, looking_for: "x", why_this_peer: "y" }),
    ev("message.sent", { id: "m2", thread_id: "t1", from_id: "b", to_id: "a", intent: "reply", body: "r", color: 0 }),
  ]);
  const [m1, m2] = s.messages.filter((m) => m.kind === "message");
  assert.deepEqual(m1.trust, { status: "verified", reason: "" });
  assert.equal(m1.lookingFor, "x");
  assert.equal(m2.replyTo, "m1");
  assert.deepEqual(s.agents.b.trust.a, { status: "verified", reason: "" });
});

test("chat items follow the thread, all-threads, agent, and range filters", () => {
  let s = run([
    ev("thread.opened", { id: "t1", owner: "a", title: "one", color: 0 }, 1),
    ev("thread.opened", { id: "t2", owner: "c", title: "two", color: 1 }, 2),
    ev("message.sent", { id: "m1", thread_id: "t1", from_id: "a", to_id: "b", intent: "request", body: "1", color: 0, ts: 3 }, 3),
    ev("message.sent", { id: "m2", thread_id: "t2", from_id: "c", to_id: "d", intent: "request", body: "2", color: 1, ts: 4 }, 4),
  ]);
  const ids = (st) => chatItems(st).filter((m) => m.kind === "message").map((m) => m.id);
  assert.deepEqual(ids(s), ["m1"]);
  assert.equal(s.threads.t2.unread, 1);
  s = select(s, { thread: "t2" });
  assert.equal(s.threads.t2.unread, 0);
  s = select(s, { allThreads: true });
  assert.deepEqual(ids(s), ["m1", "m2"]);
  s = select(s, { agent: "d" });
  assert.deepEqual(ids(s), ["m2"]);
  s = select(s, { agent: null, range: [0, 3.5] });
  assert.deepEqual(ids(s), ["m1"]);
});

test("decisions, tasks, and unknown events", () => {
  const s = run([
    agent("a.x.example"),
    ev("decision.made", { agent: "a.x.example", prompt: "Q", decision: { action: "send" }, outcome: "rejected: unknown target" }),
    ev("decision.made", { agent: "a.x.example", prompt: "P", decision: { action: "wait" }, outcome: "wait" }),
    ev("task.created", { task_id: "k1", requester: "a", recipient: "b", message_id: "m1", thread_id: "t1" }),
    ev("task.updated", { task_id: "k1", state: "completed", artifact: "done" }),
    ev("something.new", {}),
  ]);
  const a = s.agents["a.x.example"];
  assert.equal(a.lastPrompt, "P");
  assert.equal(a.decisions.length, 2);
  assert.equal(a.counters.rejected, 1);
  assert.equal(s.tasks.k1.state, "completed");
  assert.equal(s.taskByMessage.m1, "k1");
  assert.equal(s.unknown, 1);
});

test("store notifies subscribers and reset keeps the view", () => {
  const store = createStore();
  let calls = 0;
  store.subscribe(() => { calls += 1; });
  store.select({ view: "matrix" });
  store.dispatch(ev("arena.idle", { reason: "no key" }));
  store.reset();
  assert.equal(store.get().selection.view, "matrix");
  assert.equal(store.get().mode, "connecting");
  assert.equal(calls, 3);
  assert.ok(HANDLED.includes("registration.step"));
});

test("pair filter shows one direction and clears on other selections", () => {
  let s = run([
    ev("message.sent", { id: "p1", thread_id: "t1", from_id: "a", to_id: "b", intent: "share", body: "1", color: 0 }),
    ev("message.sent", { id: "p2", thread_id: "t1", from_id: "b", to_id: "a", intent: "reply", body: "2", color: 0 }),
  ]);
  s = select(s, { pair: ["a", "b"] });
  assert.deepEqual(chatItems(s).filter((m) => m.kind === "message").map((m) => m.id), ["p1"]);
  s = select(s, { thread: "t1" });
  assert.equal(s.selection.pair, null);
});

test("task updates keep the reply id", () => {
  const s = run([
    ev("task.created", { task_id: "k2", requester: "a", recipient: "b", message_id: "m1", thread_id: "t1" }),
    ev("task.updated", { task_id: "k2", state: "completed", artifact: "x", reason: "", reply_id: "m2" }),
  ]);
  assert.equal(s.tasks.k2.replyId, "m2");
});

test("generation increases on bus.reset and store reset", () => {
  const s0 = initialState();
  const s1 = apply(s0, ev("bus.reset", { run_id: "x", log: "x" }));
  assert.equal(s1.generation, s0.generation + 1);
  const store = createStore();
  const before = store.get().generation;
  store.reset();
  assert.equal(store.get().generation, before + 1);
});

test("live data is available only in live and stopped modes", () => {
  assert.equal(liveDataAvailable("live"), true);
  assert.equal(liveDataAvailable("stopped"), true);
  assert.equal(liveDataAvailable("replay"), false);
  assert.equal(liveDataAvailable("idle"), false);
});

test("thinking intervals open on decision.started and close on decision.made", () => {
  const s = run([
    agent("t.x.example"),
    ev("decision.started", { agent: "t.x.example" }, 10),
    ev("decision.made", { agent: "t.x.example", prompt: "P", decision: null, outcome: "wait" }, 12),
  ]);
  const a = s.agents["t.x.example"];
  assert.equal(a.thinking, null);
  assert.deepEqual(a.intervals, [{ start: 10, end: 12, outcome: "wait" }]);
});

test("agent.error closes an open thinking interval", () => {
  const s = run([
    agent("e.x.example"),
    ev("decision.started", { agent: "e.x.example" }, 20),
    ev("agent.error", { id: "e.x.example", error: "timeout" }, 25),
  ]);
  assert.deepEqual(s.agents["e.x.example"].intervals, [{ start: 20, end: 25, outcome: "error" }]);
  assert.equal(s.agents["e.x.example"].thinking, null);
});

test("sector, system item kinds, and focus defaults", () => {
  const s = run([
    agent("s.x.example", { sector: "member" }),
    agent("p.x.example"),
    ev("agent.verified", { id: "s.x.example" }),
    ev("thread.opened", { id: "t1", owner: "s.x.example", title: "case", color: 0 }),
    ev("arena.stopped", { reason: "done" }),
  ]);
  assert.equal(s.agents["s.x.example"].sector, "member");
  assert.equal(s.agents["p.x.example"].sector, "provider");
  assert.deepEqual(s.messages.map((m) => m.sub), ["setup", "setup", "setup", "thread", "run"]);
  assert.equal(s.selection.focus, null);
  assert.equal(s.selection.hoverMessage, null);
});
