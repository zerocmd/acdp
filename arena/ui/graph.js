// Force-directed agent graph, clustered by domain.
const STATUS_COLOR = { verified: "--ok", pending: "--pending", failed: "--bad" };

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function createGraph(el, { onNodeClick, threadColor }) {
  const nodes = new Map();
  const links = new Map();
  const graph = ForceGraph()(el)
    .nodeId("id")
    .nodeLabel((n) => `${n.name} — ${n.organization} (${n.domain})`)
    .nodeCanvasObject(drawNode)
    .nodePointerAreaPaint((n, color, ctx) => {
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.arc(n.x, n.y, 9, 0, 2 * Math.PI); ctx.fill();
    })
    .linkColor((l) => l.color)
    .linkWidth((l) => (l.critical ? 2.5 : 1))
    .linkDirectionalParticleColor((l) => l.color)
    .linkDirectionalParticleWidth(4)
    .onNodeClick((n) => onNodeClick(n.id))
    .onRenderFramePost(drawClusterLabels);

  graph.d3Force("cluster", (alpha) => {
    for (const [, members] of groups()) {
      const cx = avg(members, "x"), cy = avg(members, "y");
      for (const n of members) {
        n.vx += (cx - n.x) * 0.08 * alpha;
        n.vy += (cy - n.y) * 0.08 * alpha;
      }
    }
  });

  function groups() {
    const out = new Map();
    for (const n of nodes.values()) {
      if (!out.has(n.domain)) out.set(n.domain, []);
      out.get(n.domain).push(n);
    }
    return out;
  }
  function avg(list, key) { return list.reduce((s, n) => s + (n[key] || 0), 0) / list.length; }

  function drawNode(n, ctx) {
    ctx.beginPath(); ctx.arc(n.x, n.y, 7, 0, 2 * Math.PI);
    ctx.fillStyle = cssVar("--panel"); ctx.fill();
    ctx.lineWidth = 2.5; ctx.strokeStyle = cssVar(STATUS_COLOR[n.status] || "--pending");
    ctx.stroke();
    ctx.fillStyle = cssVar("--text"); ctx.font = "bold 7px system-ui";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(n.model === "sonnet" ? "S" : "H", n.x, n.y);
    ctx.font = "5px system-ui"; ctx.fillText(n.name, n.x, n.y + 12);
  }

  function drawClusterLabels(ctx) {
    ctx.font = "6px system-ui"; ctx.fillStyle = cssVar("--muted"); ctx.textAlign = "center";
    for (const [domain, members] of groups()) {
      const top = Math.min(...members.map((n) => n.y || 0));
      ctx.fillText(`${members[0].organization} (${domain})`, avg(members, "x"), top - 16);
    }
  }

  function refresh() {
    graph.graphData({ nodes: [...nodes.values()], links: [...links.values()] });
  }

  return {
    upsertNode(agent) {
      const node = nodes.get(agent.id);
      if (node) { Object.assign(node, agent); return; }
      nodes.set(agent.id, { ...agent, status: "pending" });
      refresh();
    },
    setStatus(id, status) {
      const node = nodes.get(id);
      if (node) node.status = status;
    },
    message(m) {
      if (!nodes.has(m.from_id) || !nodes.has(m.to_id)) return;
      const key = `${m.from_id}>${m.to_id}`;
      let link = links.get(key);
      if (!link) {
        link = { source: m.from_id, target: m.to_id };
        links.set(key, link);
        refresh();
      }
      link.critical = m.intent === "decline" || m.intent === "challenge";
      link.color = link.critical ? cssVar("--bad") : threadColor(m.color);
      graph.emitParticle(link);
    },
    reset() { nodes.clear(); links.clear(); refresh(); },
  };
}
