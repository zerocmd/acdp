// Pure layout helpers shared by the views. Node tests import this module.

export function scaleTime(t0, t1, width) {
  const span = t1 - t0;
  if (span <= 0) return { x: () => width / 2, t: () => t0 };
  return { x: (ts) => ((ts - t0) / span) * width, t: (x) => t0 + (x / width) * span };
}

export function expandPoints(points, pad) {
  return points.flatMap((p) => [
    { x: p.x - pad, y: p.y - pad }, { x: p.x + pad, y: p.y - pad },
    { x: p.x + pad, y: p.y + pad }, { x: p.x - pad, y: p.y + pad },
  ]);
}

export function convexHull(points) {
  const pts = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  if (pts.length < 3) return pts;
  const cross = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const half = (list) => {
    const out = [];
    for (const p of list) {
      while (out.length >= 2 && cross(out[out.length - 2], out[out.length - 1], p) <= 0) out.pop();
      out.push(p);
    }
    out.pop();
    return out;
  };
  return half(pts).concat(half([...pts].reverse()));
}

export function hullLabelPoint(hull) {
  return hull.reduce((best, p) => (p.y < best.y || (p.y === best.y && p.x < best.x) ? p : best), hull[0]);
}

export function threadLinks(messages) {
  const links = new Map();
  for (const m of messages) {
    if (m.kind !== "message") continue;
    const [a, b] = [m.from, m.to].sort();
    const key = `${a}|${b}|${m.threadId}`;
    if (!links.has(key)) links.set(key, { key, source: m.from, target: m.to, thread: m.threadId,
      color: m.color, count: 0, critical: false, curvature: 0 });
    const link = links.get(key);
    link.count += 1;
    if (m.intent === "decline" || m.intent === "challenge") link.critical = true;
  }
  const perPair = new Map();
  for (const link of links.values()) {
    const pair = [link.source, link.target].sort().join("|");
    const i = perPair.get(pair) || 0;
    perPair.set(pair, i + 1);
    link.curvature = i === 0 ? 0 : (i % 2 ? 1 : -1) * 0.25 * Math.ceil(i / 2);
  }
  return [...links.values()];
}

export function matrixCells(messages, ids) {
  const cells = {};
  let max = 0;
  for (const m of messages) {
    if (m.kind !== "message") continue;
    const key = `${m.from}>${m.to}`;
    const cell = cells[key] || (cells[key] = { count: 0, failed: false, verified: false, bodies: [] });
    cell.count += 1;
    if (m.trust?.status === "failed") cell.failed = true;
    if (m.trust?.status === "verified") cell.verified = true;
    if (cell.bodies.length < 5) cell.bodies.push(`${m.intent}: ${m.body}`);
    max = Math.max(max, cell.count);
  }
  return { ids, cells, max };
}

export function flowGraph(messages, threadId) {
  const ms = messages.filter((m) => m.kind === "message" && m.threadId === threadId);
  const nodes = [];
  const edges = new Map();
  for (const m of ms) {
    for (const id of [m.from, m.to]) if (!nodes.includes(id)) nodes.push(id);
    const key = `${m.from}>${m.to}`;
    if (!edges.has(key)) edges.set(key, { from: m.from, to: m.to, count: 0, intents: [] });
    const e = edges.get(key);
    e.count += 1;
    if (!e.intents.includes(m.intent)) e.intents.push(m.intent);
  }
  return { nodes, edges: [...edges.values()], root: ms[0]?.from || null };
}

export function sequenceRows(messages, markers) {
  const items = [
    ...messages.filter((m) => m.kind === "message").map((m) => ({ ...m, kind: "message" })),
    ...markers.map((m) => ({ ...m, kind: "marker" })),
  ].sort((a, b) => a.seq - b.seq);
  return items.map((item, index) => ({ ...item, index }));
}
