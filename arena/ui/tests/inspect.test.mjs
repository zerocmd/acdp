import { test } from "node:test";
import assert from "node:assert/strict";
import { apply, initialState } from "../store.js";
import { inScope, normScope, pairScope, scopeAgents, scopeKey, scopeLabel, scopeMessages,
  summarize, summaryRequest, switchPairLevel } from "../lib/inspect.js";

let seq = 0;
const ev = (type, data, ts) => ({ seq: seq++, ts, run_id: "r", type, data });
const reg = (id, name, organization, extra = {}) => ev("agent.registered", {
  id, slug: id.split(".")[0], name, organization, domain: id.split(".").slice(1).join("."),
  capability: "cap", model: "haiku", role: "agenda", did: "did", needs: [], system_prompt: "", ...extra }, 1);
const sent = (id, from, to, thread, intent, body, ts, extra = {}) => ev("message.sent", {
  id, from_id: from, to_id: to, thread_id: thread, intent, body, color: 0, ...extra }, ts);

const SOC = "soc.n.example";
const INTEL = "intel.h.example";
const FAKE = "fake.h1.example";
const ISAC = "isac.i.example";

// One phishing thread (t1) with a request, a reply, an impostor share, a decline, and a
// verdict; and one unanswered request on t2.
function scenario() {
  const events = [
    reg(SOC, "SOC", "Northgate", { sector: "member" }), reg(INTEL, "Intel", "Halcyon"),
    reg(FAKE, "Fake Intel", "Halcyon"), reg(ISAC, "ISAC", "FinShare", { sector: "assurance" }),
    ev("agent.verified", { id: SOC }, 2), ev("agent.verified", { id: INTEL }, 2),
    ev("agent.verification_failed", { id: FAKE, reasons: ["organization registered under h.example"] }, 2),
    ev("agent.verified", { id: ISAC }, 2),
    ev("thread.opened", { id: "t1", owner: SOC, title: "Phishing", color: 0 }, 100),
    ev("discovery.query", { agent: SOC, capability: "threat-intel",
      results: [{ id: INTEL, name: "Intel", status: "verified", new: true }] }, 101),
    sent("m1", SOC, INTEL, "t1", "request", "Do these domains match a campaign?", 102,
      { looking_for: "attribution", why_this_peer: "verified intel" }),
    ev("task.created", { task_id: "k1", requester: SOC, recipient: INTEL, message_id: "m1", thread_id: "t1" }, 102),
    sent("m2", INTEL, SOC, "t1", "reply", "Both match InvoiceDrop.", 110),
    ev("verification.peer_check", { agent: SOC, sender: INTEL, status: "verified", message_id: "m2" }, 110),
    ev("task.updated", { task_id: "k1", state: "completed", reply_id: "m2" }, 110),
    sent("m3", FAKE, SOC, "t1", "share", "Copy me on your findings.", 120),
    ev("verification.peer_check", { agent: SOC, sender: FAKE, status: "failed", reason: "domain mismatch", message_id: "m3" }, 120),
    sent("m4", SOC, FAKE, "t1", "decline", "Your domain does not match Halcyon.", 125),
    sent("m5", ISAC, SOC, "t1", "verdict", "InvoiceDrop phishing. Revoke tokens.", 140),
    ev("thread.closed", { id: "t1", reason: "verdict" }, 141),
    ev("thread.opened", { id: "t2", owner: INTEL, title: "Feed", color: 1 }, 150),
    sent("m6", INTEL, ISAC, "t2", "request", "Want our feed?", 151),
    ev("arena.idle", { reason: "x" }, 400),
  ];
  return events.reduce((s, e) => apply(s, e), initialState());
}

test("store records event times on threads, tasks, and the latest event", () => {
  const s = scenario();
  assert.equal(s.lastTs, 400);
  assert.deepEqual([s.threads.t1.opened, s.threads.t1.closedAt], [100, 141]);
  assert.deepEqual([s.tasks.k1.created, s.tasks.k1.updated], [102, 110]);
});

test("normScope accepts a thread id string", () => {
  assert.deepEqual(normScope("t1"), { kind: "thread", id: "t1" });
  assert.equal(normScope(null), null);
  const pair = pairScope(SOC, INTEL);
  assert.deepEqual([pair.a, pair.b, pair.level], [INTEL, SOC, "agent"]);
  assert.equal(scopeKey(pair), `pair:agent:${INTEL}|${SOC}`);
  assert.equal(scopeKey("t1"), "thread:t1");
});

test("inScope and scopeMessages follow each scope kind", () => {
  const s = scenario();
  const ids = (scope) => scopeMessages(s, scope).map((m) => m.id);
  assert.deepEqual(ids("t1"), ["m1", "m2", "m3", "m4", "m5"]);
  assert.deepEqual(ids({ kind: "org", domain: "h1.example" }), ["m3", "m4"]);
  assert.deepEqual(ids(pairScope(SOC, INTEL)), ["m1", "m2"]);
  assert.deepEqual(ids(pairScope("n.example", "h.example", "org")), ["m1", "m2"]);
  assert.deepEqual(ids({ kind: "agent", id: ISAC }), ["m5", "m6"]);
  assert.equal(inScope(null, { from: SOC, to: INTEL, threadId: "t9" }, s.agents), true);
  s.selection.range = [100, 111];
  assert.deepEqual(ids("t1"), ["m1", "m2"]);
});

test("scopeAgents and scopeLabel", () => {
  const s = scenario();
  assert.deepEqual([...scopeAgents(s, { kind: "org", domain: "n.example" })].sort(), [FAKE, INTEL, ISAC, SOC].sort());
  assert.deepEqual([...scopeAgents(s, "t2")].sort(), [INTEL, ISAC].sort());
  assert.equal(scopeLabel(s, pairScope(SOC, INTEL)), "Intel ↔ SOC");
  assert.equal(scopeLabel(s, pairScope("n.example", "h.example", "org")), "Halcyon ↔ Northgate");
  assert.equal(scopeLabel(s, "t1"), "t1 Phishing");
  assert.equal(scopeLabel(s, { kind: "org", domain: "i.example" }), "FinShare");
});

test("switchPairLevel goes to organizations and back to the busiest agent pair", () => {
  const s = scenario();
  const org = switchPairLevel(s, pairScope(SOC, INTEL));
  assert.deepEqual([org.a, org.b, org.level], ["h.example", "n.example", "org"]);
  const back = switchPairLevel(s, org);
  assert.deepEqual([back.a, back.b, back.level], [INTEL, SOC, "agent"]);
});

test("summarize a closed thread", () => {
  const sum = summarize(scenario(), "t1");
  assert.equal(sum.headline, "t1 Phishing: 5 messages in 1 thread · request answered in 8 s · closed by verdict");
  assert.deepEqual(sum.opening, { text: "Do these domains match a campaign?", lookingFor: "attribution" });
  assert.deepEqual(sum.latest, { from: "ISAC", intent: "verdict", text: "InvoiceDrop phishing. Revoke tokens." });
  assert.equal(sum.outcome, "InvoiceDrop phishing. Revoke tokens.");
  assert.deepEqual(sum.flags, ["trust-failure", "impostor-contact"]);
  assert.equal(sum.count, 5);
});

test("summarize flags an unanswered request and a decline", () => {
  const s = scenario();
  const t2 = summarize(s, "t2");
  assert.deepEqual(t2.flags, ["unanswered"]);
  assert.equal(t2.outcome, "open");
  const fake = summarize(s, pairScope(SOC, FAKE));
  assert.equal(fake.outcome, "declined: Your domain does not match Halcyon.");
  assert.deepEqual(fake.flags, ["trust-failure", "impostor-contact"]);
});

test("summarize handles an empty scope", () => {
  const sum = summarize(scenario(), pairScope(ISAC, FAKE));
  assert.equal(sum.count, 0);
  assert.equal(sum.headline, "Fake Intel ↔ ISAC: 0 messages in 0 threads");
  assert.deepEqual([sum.opening, sum.latest, sum.outcome, sum.flags], [null, null, "no messages", []]);
});

test("summaryRequest caps messages and truncates bodies", () => {
  const s = scenario();
  const long = s.messages.find((m) => m.id === "m1");
  long.body = "x".repeat(900);
  const body = summaryRequest(s, "t1");
  assert.equal(body.kind, "thread");
  assert.equal(body.title, "t1 Phishing");
  assert.equal(body.messages.length, 5);
  assert.equal(body.messages[0].body.length, 600);
  assert.deepEqual(Object.keys(body.messages[0]).sort(), ["body", "from_name", "from_org", "intent", "to_name", "trust", "ts"]);
  assert.equal(body.messages[2].trust, "failed");
  assert.equal(body.facts.flags, "trust-failure, impostor-contact");
});
