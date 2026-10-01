// Network view: companies as hulls, one curved edge per pair per thread,
// and a 2-second highlight for each discovery search.
import { html, useEffect, useRef } from "../preact.js";
import { companyColor, threadColor, TRUST_TOKENS } from "../palette.js";
import { convexHull, expandPoints, hullLabelPoint, threadLinks } from "../lib/layout.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const HIGHLIGHT_MS = 2000;

export function createNetwork(el, onSelect) {
  const nodes = new Map();
  let links = new Map();
  let search = { agent: null, ids: new Set(), fresh: new Set(), links: [], until: 0 };
  let selected = null;
  let lastMessageSeq = -1;
  let lastHighlightSeq = -1;
  let signature = "";

  const active = () => Date.now() < search.until;
  const graph = ForceGraph()(el)
    .nodeId("id")
    .nodeLabel((n) => `${n.name} — ${n.organization} (${n.domain})`)
    .nodeCanvasObject((n, ctx, scale) => {
      const dim = active() && n.id !== search.agent && !search.ids.has(n.id);
      ctx.globalAlpha = dim ? 0.25 : 1;
      if (active() && n.id === search.agent) {
        ctx.beginPath(); ctx.arc(n.x, n.y, 14, 0, 2 * Math.PI);
        ctx.strokeStyle = css("--search"); ctx.lineWidth = 2 / scale; ctx.stroke();
      }
      ctx.beginPath(); ctx.arc(n.x, n.y, 7, 0, 2 * Math.PI);
      ctx.fillStyle = css("--panel"); ctx.fill();
      ctx.lineWidth = n.id === selected ? 4 : 2.5;
      ctx.strokeStyle = css(TRUST_TOKENS[n.status] || "--pending"); ctx.stroke();
      ctx.fillStyle = css("--text"); ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.font = `bold ${10 / scale}px system-ui`;
      ctx.fillText(n.model === "sonnet" ? "S" : "H", n.x, n.y);
      ctx.font = `${10 / scale}px system-ui`;
      ctx.fillText(n.name, n.x, n.y + 7 + 9 / scale);
      if (active() && search.fresh.has(n.id)) {
        ctx.fillStyle = css("--search");
        ctx.fillText("new", n.x, n.y - 7 - 8 / scale);
      }
      ctx.globalAlpha = 1;
    })
    .linkColor((l) => (l.kind === "search" ? css("--search") : l.critical ? css("--bad") : threadColor(l.color)))
    .linkWidth((l) => (l.kind === "search" ? 1.5 : Math.min(6, 1 + l.count / 2)))
    .linkLineDash((l) => (l.kind === "search" ? [4, 3] : null))
    .linkCurvature((l) => l.curvature || 0)
    .linkCanvasObjectMode((l) => (l.kind === "search" ? "after" : undefined))
    .linkCanvasObject((l, ctx, scale) => {
      const s = l.source; const t = l.target;
      if (s.x == null || t.x == null) return;
      ctx.font = `${10 / scale}px system-ui`; ctx.fillStyle = css("--search");
      ctx.textAlign = "center"; ctx.fillText(l.label, (s.x + t.x) / 2, (s.y + t.y) / 2 - 4 / scale);
    })
    .linkDirectionalParticleColor((l) => (l.critical ? css("--bad") : threadColor(l.color)))
    .linkDirectionalParticleWidth(4)
    .onRenderFramePre((ctx, scale) => drawHulls(ctx, scale))
    .onNodeClick((n) => onSelect(n.id))
    .cooldownTicks(120)
    .onEngineStop(() => {
      // Zoom to fit only when agents join, not after every message.
      if (nodes.size !== fittedCount) { fittedCount = nodes.size; graph.zoomToFit(400, 60); }
    });
  let fittedCount = 0;
  graph.d3Force("charge").strength(-260);
  const fit = () => graph.width(el.clientWidth).height(el.clientHeight);
  const observer = new ResizeObserver(fit);
  observer.observe(el);
  fit();

  function drawHulls(ctx, scale) {
    const groups = new Map();
    for (const n of nodes.values()) {
      if (n.x == null) continue;
      if (!groups.has(n.domain)) groups.set(n.domain, []);
      groups.get(n.domain).push(n);
    }
    for (const [domain, members] of groups) {
      const hull = convexHull(expandPoints(members.map((n) => ({ x: n.x, y: n.y })), 22));
      const color = companyColor(domain);
      ctx.beginPath();
      hull.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
      ctx.closePath();
      ctx.fillStyle = `${color}14`; ctx.fill();
      const failed = members.every((n) => n.status === "failed");
      ctx.setLineDash(failed ? [4 / scale, 3 / scale] : []);
      ctx.strokeStyle = failed ? css("--bad") : `${color}66`; ctx.lineWidth = 1 / scale; ctx.stroke();
      ctx.setLineDash([]);
      const p = hullLabelPoint(hull);
      // Screen-constant size: the label does not grow with zoom.
      ctx.font = `${11 / scale}px system-ui`; ctx.fillStyle = css("--muted");
      ctx.textAlign = "left"; ctx.textBaseline = "bottom";
      ctx.fillText(`${members[0].organization} · ${domain}`, p.x, p.y - 2 / scale);
    }
  }

  function refresh() {
    graph.graphData({ nodes: [...nodes.values()], links: [...links.values(), ...(active() ? search.links : [])] });
  }

  function update(state) {
    selected = state.selection.agent;
    let changed = false;
    for (const id of state.order) {
      const a = state.agents[id];
      if (!nodes.has(id)) { nodes.set(id, { id }); changed = true; }
      Object.assign(nodes.get(id), { name: a.name, organization: a.organization,
        domain: a.domain, model: a.model, status: a.status });
    }
    const range = state.selection.range;
    const visible = state.messages.filter((m) => m.kind === "message" && nodes.has(m.from)
      && nodes.has(m.to) && (!range || (m.ts >= range[0] && m.ts <= range[1])));
    const sig = `${visible.length}|${range ? range.join() : ""}`;
    if (sig !== signature) {
      signature = sig;
      const next = new Map();
      for (const l of threadLinks(visible)) {
        const existing = links.get(l.key);
        // force-graph replaces source/target with node objects; keep those.
        if (existing) Object.assign(existing, { count: l.count, color: l.color,
          critical: l.critical, curvature: l.curvature });
        next.set(l.key, existing || l);
      }
      // Rebuild the graph data only when the set of links changes. Count and
      // color changes are read every frame, so they need no restart.
      const keysChanged = next.size !== links.size || [...next.keys()].some((k) => !links.has(k));
      links = next;
      if (keysChanged) changed = true;
    }
    const query = state.selection.allQueries ? state.lastQuery : state.highlight;
    if (query && query.seq > lastHighlightSeq && nodes.has(query.agent)) {
      lastHighlightSeq = query.seq;
      const hits = query.results.filter((r) => nodes.has(r.id));
      search = {
        agent: query.agent, ids: new Set(hits.map((r) => r.id)),
        fresh: new Set(hits.filter((r) => r.new).map((r) => r.id)),
        links: hits.map((r) => ({ source: query.agent, target: r.id, kind: "search", label: query.capability })),
        until: Date.now() + HIGHLIGHT_MS,
      };
      changed = true;
      setTimeout(refresh, HIGHLIGHT_MS + 50);
    }
    if (changed) refresh();
    if (!range) {
      for (const m of visible) {
        if (m.seq <= lastMessageSeq) continue;
        lastMessageSeq = m.seq;
        const [a, b] = [m.from, m.to].sort();
        const link = links.get(`${a}|${b}|${m.threadId}`);
        if (link) graph.emitParticle(link);
      }
    }
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
  return html`<div style="position:absolute;inset:0">
    <div style="position:absolute;inset:0" ref=${el}></div>
    <label class="overlay"><input type="checkbox" checked=${state.selection.allQueries}
      onChange=${(e) => store.select({ allQueries: e.target.checked })} /> show every search</label>
  </div>`;
}
