// Comms Map layout and geometry. Pure: Node tests import this module.

export const BANDS = ["member", "provider", "assurance"];
export const BAND_LABELS = { member: "Members", provider: "Providers", assurance: "Assurance" };

const PAD = 24;
const GAP = 16;
const BAND_HEAD = 28;
const MIN_BOX_W = 180;
const BOX_HEAD = 42;
const AGENT_H = 44;

export function bandOf(sector) {
  return BANDS.includes(sector) ? sector : "provider";
}

export function groupOrgs(agents) {
  const orgs = new Map();
  for (const a of agents) {
    if (!orgs.has(a.domain)) {
      orgs.set(a.domain, { domain: a.domain, organization: a.organization, band: bandOf(a.sector), agents: [] });
    }
    orgs.get(a.domain).agents.push(a);
  }
  return [...orgs.values()].map((o) => ({ ...o, failed: o.agents.every((a) => a.status === "failed") }));
}

// Share the width by organization count. A band never gets less than one box width;
// the bands at that floor drop out and the rest share what is left.
function bandWidths(counts, avail) {
  const widths = counts.map(() => 0);
  let open = counts.map((_, i) => i);
  let left = avail;
  for (;;) {
    const total = open.reduce((n, i) => n + Math.max(1, counts[i]), 0);
    const low = open.filter((i) => (left * Math.max(1, counts[i])) / total < MIN_BOX_W);
    if (!low.length) {
      for (const i of open) widths[i] = (left * Math.max(1, counts[i])) / total;
      return widths;
    }
    for (const i of low) { widths[i] = MIN_BOX_W; left -= MIN_BOX_W; }
    open = open.filter((i) => !low.includes(i));
    if (!open.length) return widths;
  }
}

export function layoutMap(agents, width) {
  const orgs = groupOrgs(agents);
  const widths = bandWidths(BANDS.map((band) => orgs.filter((o) => o.band === band).length),
    width - PAD * 2 - GAP * 2);
  let left = PAD;
  const bands = BANDS.map((band, i) => {
    const b = { band, x: left, w: widths[i] };
    left += widths[i] + GAP;
    return b;
  });
  const placed = [];
  const nodes = {};
  let height = 0;
  for (const { band, x: bandX, w: bandW } of bands) {
    const mine = orgs.filter((o) => o.band === band);
    mine.sort((a, b) => Number(a.failed) - Number(b.failed));
    const cols = Math.max(1, Math.floor((bandW + GAP) / (MIN_BOX_W + GAP)));
    const boxW = (bandW - GAP * (cols - 1)) / cols;
    let y = PAD + BAND_HEAD;
    for (let i = 0; i < mine.length; i += cols) {
      const row = mine.slice(i, i + cols);
      const rowH = Math.max(...row.map((o) => BOX_HEAD + o.agents.length * AGENT_H + 8));
      row.forEach((o, c) => {
        const box = { ...o, x: bandX + c * (boxW + GAP), y, w: boxW, h: BOX_HEAD + o.agents.length * AGENT_H + 8 };
        placed.push(box);
        o.agents.forEach((a, k) => { nodes[a.id] = { x: box.x + 26, y: y + BOX_HEAD + k * AGENT_H + AGENT_H / 2 }; });
      });
      y += rowH + GAP;
    }
    height = Math.max(height, y);
  }
  return { bands, orgs: placed, nodes, width: Math.max(width, left - GAP + PAD), height: height + PAD };
}

export function ribbonWidth(count) {
  return Math.min(18, 2 + 4 * Math.log2(1 + count));
}

export function pointOnCubic(p, c1, c2, q, t) {
  const u = 1 - t;
  const a = u * u * u; const b = 3 * u * u * t; const c = 3 * u * t * t; const d = t * t * t;
  return { x: a * p.x + b * c1.x + c * c2.x + d * q.x, y: a * p.y + b * c1.y + c * c2.y + d * q.y };
}

export function ribbonGeometry(link, nodes) {
  const p = nodes[link.source];
  const q = nodes[link.target];
  const offset = (link.curvature || 0) * 48;
  const dx = q.x - p.x;
  let c1;
  let c2;
  if (Math.abs(dx) < 60) {
    // Same column: loop out to the right so the ribbon does not cross the labels.
    const bulge = 140 + Math.abs(offset);
    c1 = { x: p.x + bulge, y: p.y + offset };
    c2 = { x: q.x + bulge, y: q.y + offset };
  } else {
    // Nearly level: sag below the row so the ribbon does not cross its labels.
    const sag = Math.abs(q.y - p.y) < 40 ? Math.min(160, 40 + Math.abs(dx) * 0.15) : 0;
    c1 = { x: p.x + dx * 0.5, y: p.y + offset + sag };
    c2 = { x: q.x - dx * 0.5, y: q.y + offset + sag };
  }
  const f = (n) => Math.round(n * 10) / 10;
  const d = `M${f(p.x)},${f(p.y)} C${f(c1.x)},${f(c1.y)} ${f(c2.x)},${f(c2.y)} ${f(q.x)},${f(q.y)}`;
  return { p, c1, c2, q, d, mid: pointOnCubic(p, c1, c2, q, 0.5) };
}

export function placePopup(active, anchor, size, bounds) {
  const clampX = (x) => Math.min(Math.max(0, x), Math.max(0, bounds.w - size.w));
  const clampY = (y) => Math.min(Math.max(0, y), Math.max(0, bounds.h - size.h));
  const x = clampX(anchor.x - size.w / 2);
  const hits = (y) => active.some((r) => x < r.x + r.w && r.x < x + size.w && y < r.y + r.h && r.y < y + size.h);
  let y = clampY(anchor.y - size.h - 10);
  for (let i = 0; i < 12 && hits(y); i += 1) y = clampY(y + size.h + 6);
  if (hits(y)) {
    y = clampY(anchor.y - size.h - 10);
    for (let i = 0; i < 12 && hits(y); i += 1) y = clampY(y - size.h - 6);
  }
  return { x, y };
}

export function freshEvents(items, sinceSeq) {
  return items.filter((e) => e.seq > sinceSeq);
}

export function capQueue(queue, item, max) {
  const next = [...queue, item];
  return next.length > max ? next.slice(next.length - max) : next;
}

// Screen size of a popup card slot. Cards have a 2-line header and a 3-line body.
export function popupBox(scale = 1) {
  return { w: Math.round(250 * scale), h: Math.round(130 * scale) };
}

// Move organization boxes and their agent nodes by per-domain offsets
// ({domain: {dx, dy}}). Returns a new layout; the input stays unchanged.
export function applyOffsets(layout, offsets) {
  if (!Object.keys(offsets).length) return layout;
  const nodes = { ...layout.nodes };
  const orgs = layout.orgs.map((o) => {
    const off = offsets[o.domain];
    if (!off) return o;
    for (const a of o.agents) {
      const n = nodes[a.id];
      if (n) nodes[a.id] = { x: n.x + off.dx, y: n.y + off.dy };
    }
    return { ...o, x: o.x + off.dx, y: o.y + off.dy };
  });
  return { ...layout, orgs, nodes };
}
