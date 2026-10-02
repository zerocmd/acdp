// Sequence view time axis, arrow widths, and lane filtering. Pure.
export const GAP_S = 20;

export function layoutRows(items, { pxPerSec = 6, minStep = 28, maxStep = 120, gapS = GAP_S, spacer = 26 } = {}) {
  const sorted = [...items].sort((a, b) => a.ts - b.ts || a.seq - b.seq);
  const rows = [];
  const spacers = [];
  let y = 0;
  let prev = null;
  for (const item of sorted) {
    if (prev !== null) {
      const dt = item.ts - prev;
      if (dt > gapS) {
        y += minStep;
        spacers.push({ y, seconds: Math.round(dt) });
        y += spacer;
      } else {
        y += Math.min(maxStep, Math.max(minStep, dt * pxPerSec));
      }
    }
    rows.push({ ...item, y });
    prev = item.ts;
  }
  return { rows, spacers, height: y + minStep };
}

export function yAtTime(rows, ts) {
  if (!rows.length) return 0;
  if (ts <= rows[0].ts) return rows[0].y;
  const last = rows[rows.length - 1];
  if (ts >= last.ts) return last.y;
  for (let i = 0; i < rows.length - 1; i += 1) {
    const a = rows[i];
    const b = rows[i + 1];
    if (ts >= a.ts && ts <= b.ts) return b.ts === a.ts ? a.y : a.y + ((ts - a.ts) / (b.ts - a.ts)) * (b.y - a.y);
  }
  return last.y;
}

export function arrowWidth(body) {
  const n = (body || "").length;
  return n < 120 ? 2 : n < 400 ? 3.5 : 5;
}

export function visibleLanes(ids, messages, { focus = null, range = null, showAll = false } = {}) {
  if (showAll) return ids;
  const active = new Set();
  for (const m of messages) {
    if (focus && m.threadId !== focus) continue;
    if (range && (m.ts < range[0] || m.ts > range[1])) continue;
    active.add(m.from);
    active.add(m.to);
  }
  const lanes = ids.filter((id) => active.has(id));
  return lanes.length ? lanes : ids;
}
