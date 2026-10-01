// Network view: force-directed graph clustered by domain.
import { html, useEffect, useRef } from "../preact.js";
import { companyColor, threadColor, TRUST_TOKENS } from "../palette.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function createNetwork(el, onSelect) {
  const nodes = new Map();
  const links = new Map();
  let lastMessageSeq = -1;
  const graph = ForceGraph()(el)
    .nodeId("id")
    .nodeLabel((n) => `${n.name} — ${n.organization} (${n.domain})`)
    .nodeCanvasObject((n, ctx, scale) => {
      ctx.beginPath(); ctx.arc(n.x, n.y, 7, 0, 2 * Math.PI);
      ctx.fillStyle = css("--panel"); ctx.fill();
      ctx.lineWidth = 2.5; ctx.strokeStyle = css(TRUST_TOKENS[n.status] || "--pending"); ctx.stroke();
      ctx.fillStyle = css("--text"); ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.font = `bold ${10 / scale}px system-ui`;
      ctx.fillText(n.model === "sonnet" ? "S" : "H", n.x, n.y);
      ctx.font = `${10 / scale}px system-ui`;
      ctx.fillText(n.name, n.x, n.y + 7 + 9 / scale);
    })
    .linkColor((l) => l.color)
    .linkWidth((l) => Math.min(6, 1 + l.count / 2))
    .linkDirectionalParticleColor((l) => l.color)
    .linkDirectionalParticleWidth(4)
    .onNodeClick((n) => onSelect(n.id))
    .cooldownTicks(120)
    .onEngineStop(() => {
      if (nodes.size !== fittedCount) { fittedCount = nodes.size; graph.zoomToFit(400, 60); }
    });
  let fittedCount = 0;
  graph.d3Force("charge").strength(-260);
  const fit = () => graph.width(el.clientWidth).height(el.clientHeight);
  const observer = new ResizeObserver(fit);
  observer.observe(el);
  fit();

  function update(state) {
    let changed = false;
    for (const id of state.order) {
      const a = state.agents[id];
      if (!nodes.has(id)) { nodes.set(id, { id }); changed = true; }
      Object.assign(nodes.get(id), { name: a.name, organization: a.organization,
        domain: a.domain, model: a.model, status: a.status });
    }
    const fresh = [];
    for (const m of state.messages) {
      if (m.kind !== "message" || m.seq <= lastMessageSeq) continue;
      lastMessageSeq = m.seq;
      if (!nodes.has(m.from) || !nodes.has(m.to)) continue;
      const key = `${m.from}>${m.to}`;
      if (!links.has(key)) { links.set(key, { source: m.from, target: m.to, count: 0 }); changed = true; }
      const link = links.get(key);
      link.count += 1;
      const critical = m.intent === "decline" || m.intent === "challenge";
      link.color = critical ? css("--bad") : threadColor(m.color);
      fresh.push(link);
    }
    // A particle needs its link in the graph data, so update the data first.
    if (changed) graph.graphData({ nodes: [...nodes.values()], links: [...links.values()] });
    fresh.forEach((link) => graph.emitParticle(link));
  }

  return { graph, update, destroy() { observer.disconnect(); graph._destructor?.(); } };
}

export function NetworkView({ store, state }) {
  const el = useRef(null);
  const net = useRef(null);
  useEffect(() => {
    net.current = createNetwork(el.current, (id) => store.select({ agent: id, tab: "overview" }));
    return () => net.current.destroy();
  }, []);
  useEffect(() => { net.current.update(state); });
  return html`<div style="position:absolute;inset:0" ref=${el}></div>`;
}
