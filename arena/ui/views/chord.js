// Chord ring: organizations as arcs, agents as points on the ring, ribbons as chords.
import { html, useEffect, useRef, useState } from "../preact.js";
import { companyColor, threadColor } from "../palette.js";
import { threadLinks } from "../lib/layout.js";
import { groupOrgs, ribbonWidth } from "../lib/commsmap.js";
import { chordGeometry, chordLayout } from "../lib/chord.js";
import { linkKey, mapMessages } from "./commsmap.js";
import { inScope, normScope, pairScope } from "../lib/inspect.js";

function arcPath(cx, cy, r, a0, a1) {
  const p0 = { x: cx + r * Math.cos(a0), y: cy + r * Math.sin(a0) };
  const p1 = { x: cx + r * Math.cos(a1), y: cy + r * Math.sin(a1) };
  return `M${p0.x},${p0.y} A${r},${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${p1.x},${p1.y}`;
}

export function ChordView({ store, state }) {
  const box = useRef(null);
  const [size, setSize] = useState({ w: 900, h: 700 });
  useEffect(() => {
    const measure = () => setSize({ w: box.current.clientWidth || 900, h: box.current.clientHeight || 700 });
    const observer = new ResizeObserver(measure);
    observer.observe(box.current);
    measure();
    return () => observer.disconnect();
  }, []);
  const cx = size.w / 2;
  const cy = size.h / 2;
  const r = Math.max(120, Math.min(size.w, size.h) / 2 - 90);
  const orgs = groupOrgs(state.order.map((id) => state.agents[id]));
  const { arcs, anchors } = chordLayout(orgs, cx, cy, r);
  const focus = normScope(state.selection.focus);
  const links = threadLinks(mapMessages(state)).filter((l) => anchors[l.source] && anchors[l.target]);
  const hover = state.selection.hoverMessage && state.messages.find((m) => m.id === state.selection.hoverMessage);
  const hoverKey = hover ? linkKey(hover.from, hover.to, hover.threadId) : null;
  return html`<div class="map" ref=${box}>
    <svg width="100%" height="100%">
      ${arcs.map((a) => html`<g class=${`chord-arc${a.failed ? " failed" : ""}`}
        onClick=${() => store.select({ inspect: { kind: "org", domain: a.domain } })}>
        <path d=${arcPath(cx, cy, r + 14, a.start, a.end)} style=${`stroke:${a.failed ? "var(--bad)" : companyColor(a.domain)}`} />
        <text x=${cx + (r + 40) * Math.cos((a.start + a.end) / 2)} y=${cy + (r + 40) * Math.sin((a.start + a.end) / 2)}>${a.organization}</text>
      </g>`)}
      ${links.map((l) => {
        const g = chordGeometry(anchors[l.source], anchors[l.target], { x: cx, y: cy });
        const key = linkKey(l.source, l.target, l.thread);
        return html`<path class=${`ribbon${l.critical ? " critical" : ""}${focus && !inScope(focus, { from: l.source, to: l.target, threadId: l.thread }, state.agents) ? " dim" : ""}${key === hoverKey ? " glow" : ""}`}
          d=${g.d} stroke-width=${ribbonWidth(l.count)} style=${`--rc:${l.critical ? "var(--bad)" : threadColor(l.color)}`}
          onClick=${() => store.select({ focus: l.thread, thread: l.thread, allThreads: false,
            inspect: pairScope(l.source, l.target, "agent") })} />`;
      })}
      ${Object.entries(anchors).map(([id, p]) => html`<circle class="chord-agent" cx=${p.x} cy=${p.y} r="6"
        style=${`fill:${companyColor(state.agents[id].domain)}`} onClick=${() => store.select({ agent: id, tab: "overview" })}>
        <title>${state.agents[id].name}</title></circle>`)}
    </svg>
  </div>`;
}
