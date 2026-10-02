// Chord ring layout. Pure.
import { pointOnCubic } from "./commsmap.js";

const GAP = 0.04;

export function chordLayout(orgs, cx, cy, r) {
  const total = orgs.reduce((n, o) => n + o.agents.length, 0) || 1;
  const usable = 2 * Math.PI - GAP * orgs.length;
  let angle = -Math.PI / 2;
  const arcs = [];
  const anchors = {};
  for (const o of orgs) {
    const span = (usable * o.agents.length) / total;
    arcs.push({ domain: o.domain, organization: o.organization, start: angle, end: angle + span, failed: o.failed });
    o.agents.forEach((a, i) => {
      const t = angle + (span * (i + 0.5)) / o.agents.length;
      anchors[a.id] = { x: cx + r * Math.cos(t), y: cy + r * Math.sin(t), angle: t };
    });
    angle += span + GAP;
  }
  return { arcs, anchors };
}

export function chordGeometry(a, b, center) {
  const pull = (p) => ({ x: center.x + (p.x - center.x) * 0.25, y: center.y + (p.y - center.y) * 0.25 });
  const c1 = pull(a);
  const c2 = pull(b);
  const f = (n) => Math.round(n * 10) / 10;
  return { p: a, c1, c2, q: b, d: `M${f(a.x)},${f(a.y)} C${f(c1.x)},${f(c1.y)} ${f(c2.x)},${f(c2.y)} ${f(b.x)},${f(b.y)}`,
    mid: pointOnCubic(a, c1, c2, b, 0.5) };
}
