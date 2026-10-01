// Flow view: one thread as a layered graph, left to right. Loops curve back.
import { html, useMemo } from "../preact.js";
import { chatItems } from "../store.js";
import { flowGraph } from "../lib/layout.js";

const NODE_W = 140;
const NODE_H = 36;

function layoutFlow(g) {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: "LR", nodesep: 30, ranksep: 90, marginx: 20, marginy: 20 });
  graph.setDefaultEdgeLabel(() => ({}));
  g.nodes.forEach((id) => graph.setNode(id, { width: NODE_W, height: NODE_H }));
  g.edges.forEach((e) => graph.setEdge(e.from, e.to, { ...e, width: 70, height: 14 }));
  dagre.layout(graph);
  const nodes = graph.nodes().map((id) => ({ id, ...graph.node(id) }));
  const x = new Map(nodes.map((n) => [n.id, n.x]));
  const edges = graph.edges().map((k) => {
    const e = graph.edge(k);
    return { ...e, back: x.get(e.from) > x.get(e.to) };
  });
  return { nodes, edges, width: graph.graph().width || 0, height: graph.graph().height || 0 };
}

function pathFor(points) {
  const [first, ...rest] = points;
  if (rest.length < 2) return `M${first.x},${first.y} L${rest.map((p) => `${p.x},${p.y}`).join(" ")}`;
  let d = `M${first.x},${first.y}`;
  for (let i = 0; i < rest.length - 1; i += 1) {
    const mid = { x: (rest[i].x + rest[i + 1].x) / 2, y: (rest[i].y + rest[i + 1].y) / 2 };
    d += ` Q${rest[i].x},${rest[i].y} ${mid.x},${mid.y}`;
  }
  const end = rest[rest.length - 1];
  return `${d} L${end.x},${end.y}`;
}

export function FlowView({ store, state }) {
  const { allThreads, thread } = state.selection;
  const threadId = allThreads ? (state.threads.t1 ? "t1" : state.threadOrder[0]) : thread;
  const messages = chatItems({ ...state, selection: { ...state.selection, allThreads: true, agent: null, pair: null } });
  const g = flowGraph(messages, threadId);
  const layout = useMemo(() => (g.nodes.length ? layoutFlow(g) : null),
    [state.lastSeq, threadId, String(state.selection.range)]);
  if (!layout) return html`<p class="muted" style="padding:12px">No messages on ${threadId || "this thread"} yet.</p>`;
  const name = (id) => state.agents[id]?.name || id;
  return html`<div class="view scroll">
    <p class="muted" style="margin:6px 12px">Thread ${threadId}: ${state.threads[threadId]?.title || ""}${allThreads ? " (flow shows one thread)" : ""}</p>
    <svg class="flow" width=${layout.width + 40} height=${layout.height + 40}>
      <defs><marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
        orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="flow-head" /></marker></defs>
      ${layout.edges.map((e) => {
        const mid = e.points[Math.floor(e.points.length / 2)];
        const bad = e.intents.includes("decline") || e.intents.includes("challenge");
        return html`<g>
          <path d=${pathFor(e.points)} class=${`flow-edge${e.back ? " back" : ""}${bad ? " bad" : ""}${e.intents.includes("verdict") ? " verdict" : ""}`}
            marker-end="url(#flow-arrow)" />
          <text x=${mid.x} y=${mid.y - 4} class="flow-label">${e.intents.join("/")} ×${e.count}</text>
        </g>`;
      })}
      ${layout.nodes.map((n) => {
        const a = state.agents[n.id] || {};
        return html`<g class="flow-node" onClick=${() => store.select({ agent: n.id, tab: "overview" })}>
          <rect x=${n.x - NODE_W / 2} y=${n.y - NODE_H / 2} width=${NODE_W} height=${NODE_H} rx="8"
            class=${`flow-box ${a.status || ""}${n.id === g.root ? " root" : ""}${n.id === state.selection.agent ? " selected" : ""}`} />
          <text x=${n.x} y=${n.y + 4} class="flow-name">${name(n.id)}</text>
        </g>`;
      })}
    </svg>
  </div>`;
}
