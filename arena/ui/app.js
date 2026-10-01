// Event store: one WebSocket stream drives the graph, transcript, and controls.
import { createControls } from "./controls.js";
import { createGraph } from "./graph.js";
import { createTranscript } from "./transcript.js";

const COLORS = ["#3b5bdb", "#0ca678", "#f08c00", "#7048e8", "#1098ad", "#e8590c",
  "#5c940d", "#c2255c", "#495057", "#1c7ed6", "#9c36b5", "#2b8a3e"];
const threadColor = (i) => COLORS[(i ?? 0) % COLORS.length];
const $ = (id) => document.getElementById(id);

const state = { agents: new Map(), threads: new Map(), messages: 0, lastSeq: -1 };
const nameOf = (id) => state.agents.get(id)?.name || id;
const companyOf = (id) => state.agents.get(id)?.organization || "";

const controls = createControls();
const transcript = createTranscript($("feed"), {
  thread: $("f-thread"), agent: $("f-agent"), company: $("f-company"), intent: $("f-intent"),
}, { threadColor, companyOf });
const graph = createGraph($("graph"), {
  onNodeClick: (id) => transcript.setFilter("agent", id),
  threadColor,
});
$("f-clear").addEventListener("click", () => transcript.clearFilters());

function reset() {
  state.agents.clear(); state.threads.clear(); state.messages = 0; state.lastSeq = -1;
  graph.reset(); transcript.reset();
}

function stats() {
  const open = [...state.threads.values()].filter((t) => !t.closed).length;
  controls.setStats({ agents: state.agents.size, messages: state.messages, threads: open });
}

function handle(event) {
  if (event.type === "bus.reset") {
    reset();
    controls.setMode(`replay ${event.data.log || ""}`);
    state.lastSeq = event.seq;
    return;
  }
  if (event.seq <= state.lastSeq) return;
  state.lastSeq = event.seq;
  const d = event.data;
  switch (event.type) {
    case "arena.started": controls.setMode("live"); transcript.system(`Arena started with ${d.agents} agents.`); break;
    case "arena.idle": controls.setMode("idle"); transcript.system(`Arena idle: ${d.reason}`); break;
    case "arena.paused": controls.setPaused(true); transcript.system("Arena paused."); break;
    case "arena.resumed": controls.setPaused(false); transcript.system("Arena resumed."); break;
    case "arena.stopped": controls.setMode("stopped"); transcript.system(`Arena stopped: ${d.reason}`); break;
    case "agent.registered":
      state.agents.set(d.id, d);
      graph.upsertNode(d);
      transcript.addOption("agent", d.id, d.name);
      transcript.addOption("company", d.organization, d.organization);
      transcript.system(`${d.name} (${d.organization}, ${d.domain}) joined. Model: ${d.model}.`);
      break;
    case "agent.verified":
      graph.setStatus(d.id, "verified");
      transcript.system(`${nameOf(d.id)} verified by the registry.`);
      break;
    case "agent.verification_failed":
      graph.setStatus(d.id, "failed");
      transcript.system(`${nameOf(d.id)} failed verification: ${(d.reasons || []).join("; ")}`);
      break;
    case "agent.error": transcript.system(`${nameOf(d.id)} error: ${d.error}`); break;
    case "discovery.query": break; // frequent; not shown in the transcript
    case "thread.opened":
      state.threads.set(d.id, { ...d, closed: false });
      transcript.addOption("thread", d.id, `${d.id} ${d.title}`);
      transcript.system(`Thread ${d.id} opened by ${nameOf(d.owner)}: ${d.title}`);
      break;
    case "thread.closed":
      if (state.threads.has(d.id)) state.threads.get(d.id).closed = true;
      transcript.system(`Thread ${d.id} closed (${d.reason}).`);
      break;
    case "message.sent":
      state.messages += 1;
      graph.message(d);
      transcript.add({ thread: d.thread_id, color: d.color, from: d.from_id, to: d.to_id,
        intent: d.intent, text: d.body });
      break;
    case "message.failed": transcript.system(`Message ${nameOf(d.from_id)} → ${nameOf(d.to_id)} failed: ${d.error}`); break;
    case "verification.peer_check":
      if (d.status !== "verified") {
        transcript.system(`${nameOf(d.agent)} rejected trust in ${nameOf(d.sender)}: ${d.reason}`);
      }
      break;
    case "decision.rejected": break; // runtime detail; visible in the log
    default: break;
  }
  stats();
}

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws`);
  socket.onopen = () => reset(); // the server resends the full history
  socket.onmessage = (m) => handle(JSON.parse(m.data));
  socket.onclose = () => { controls.setMode("reconnecting"); setTimeout(connect, 2000); };
}
connect();
