// Comms Map: organizations in sector bands, agents in their boxes, one ribbon per
// agent pair per thread. Zoom with the wheel, pan by dragging, focus a thread to
// dim the rest. Task 7 adds the animations.
import { html, useEffect, useMemo, useRef, useState } from "../preact.js";
import { companyColor, threadColor, TRUST_TOKENS } from "../palette.js";
import { threadLinks } from "../lib/layout.js";
import { BAND_LABELS, layoutMap, ribbonGeometry, ribbonWidth } from "../lib/commsmap.js";
import { useMapEffects } from "./mapfx.js";

export const linkKey = (a, b, thread) => `${[a, b].sort().join("|")}|${thread}`;
const nodeRadius = (n) => Math.min(20, 14 + 2 * Math.log2(1 + n));
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export function mapMessages(state) {
  const range = state.selection.range;
  return state.messages.filter((m) => m.kind === "message"
    && (!range || (m.ts >= range[0] && m.ts <= range[1])));
}

export function CommsMapView({ store, state }) {
  const box = useRef(null);
  const drag = useRef(null);
  const [size, setSize] = useState({ w: 1000, h: 700 });
  const [view, setView] = useState({ k: 1, x: 0, y: 0 });
  useEffect(() => {
    const measure = () => setSize({ w: box.current.clientWidth || 1000, h: box.current.clientHeight || 700 });
    const observer = new ResizeObserver(measure);
    observer.observe(box.current);
    measure();
    return () => observer.disconnect();
  }, []);

  const agents = state.order.map((id) => state.agents[id]);
  const statusKey = agents.map((a) => `${a.id}:${a.status}:${a.sector}`).join("|");
  const layout = useMemo(() => layoutMap(agents, size.w), [statusKey, size.w]);
  const fit = () => setView({ k: clamp(Math.min(size.w / layout.width, size.h / layout.height, 1), 0.4, 1), x: 0, y: 0 });
  useEffect(fit, [agents.length, size.w, size.h]);

  useEffect(() => {
    const move = (e) => {
      if (!drag.current) return;
      setView((v) => ({ ...v, x: drag.current.vx + e.clientX - drag.current.x, y: drag.current.vy + e.clientY - drag.current.y }));
    };
    const up = () => { drag.current = null; };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
  }, []);
  const onWheel = (e) => {
    e.preventDefault();
    const r = box.current.getBoundingClientRect();
    const mx = e.clientX - r.left;
    const my = e.clientY - r.top;
    setView((v) => {
      const k = clamp(v.k * (e.deltaY < 0 ? 1.1 : 1 / 1.1), 0.4, 4);
      return { k, x: mx - ((mx - v.x) * k) / v.k, y: my - ((my - v.y) * k) / v.k };
    });
  };
  const onDown = (e) => {
    if (e.target.closest(".node, .ribbon, .badge, .map-tools")) return;
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
  };

  const messages = mapMessages(state);
  const links = threadLinks(messages).filter((l) => layout.nodes[l.source] && layout.nodes[l.target]);
  const byKey = new Map();
  for (const m of messages) {
    const key = linkKey(m.from, m.to, m.threadId);
    if (!byKey.has(key)) byKey.set(key, []);
    byKey.get(key).push(m);
  }
  const activity = {};
  for (const m of messages) {
    activity[m.from] = (activity[m.from] || 0) + 1;
    activity[m.to] = (activity[m.to] || 0) + 1;
  }
  const focus = state.selection.focus;
  const inFocus = new Set();
  if (focus) {
    for (const m of messages) if (m.threadId === focus) { inFocus.add(m.from); inFocus.add(m.to); }
    if (state.threads[focus]) inFocus.add(state.threads[focus].owner);
  }
  const hover = state.selection.hoverMessage && state.messages.find((m) => m.id === state.selection.hoverMessage);
  const hoverKey = hover ? linkKey(hover.from, hover.to, hover.threadId) : null;
  const css = (name) => `var(${name})`;
  const scene = { layout, links, byKey, view, focus, inFocus };
  const effects = useMapEffects(state, scene);

  return html`<div class="map" ref=${box} onWheel=${onWheel} onMouseDown=${onDown}>
    <div class="map-tools">
      <button onClick=${fit}>Fit</button>
      ${focus ? html`<button class="pill" style="--tone:var(--accent)" onClick=${() => store.select({ focus: null })}>
        Focus: ${focus} ${state.threads[focus]?.title?.slice(0, 32) || ""} ×</button>` : null}
      <label><input type="checkbox" checked=${state.selection.allQueries}
        onChange=${(e) => store.select({ allQueries: e.target.checked })} /> show every search</label>
    </div>
    <svg class="map-svg" width="100%" height="100%">
      <g transform=${`translate(${view.x},${view.y}) scale(${view.k})`}>
        ${layout.bands.map((b) => html`<text class="band-label" x=${b.x} y="34">${BAND_LABELS[b.band]}</text>`)}
        ${layout.orgs.map((o) => html`<g class=${`org${o.failed ? " failed" : ""}`}>
          <rect x=${o.x} y=${o.y} width=${o.w} height=${o.h} rx="10"
            style=${`--tone:${o.failed ? css("--bad") : companyColor(o.domain)}`} />
          <text class="org-label" x=${o.x + 10} y=${o.y + 18}>${o.organization}</text>
          <text class="org-domain" x=${o.x + 10} y=${o.y + 33}>${o.domain}</text>
        </g>`)}
        ${links.map((l) => {
          const g = ribbonGeometry(l, layout.nodes);
          const key = linkKey(l.source, l.target, l.thread);
          const dim = focus && l.thread !== focus;
          return html`<path class=${`ribbon${l.critical ? " critical" : ""}${dim ? " dim" : ""}${key === hoverKey ? " glow" : ""}`}
            d=${g.d} stroke-width=${ribbonWidth(l.count)} style=${`--rc:${l.critical ? css("--bad") : threadColor(l.color)}`}
            onClick=${() => store.select({ focus: l.thread, thread: l.thread, allThreads: false })}>
            <title>${l.thread}: ${l.count} messages</title></path>`;
        })}
        ${links.map((l) => {
          const g = ribbonGeometry(l, layout.nodes);
          const list = byKey.get(linkKey(l.source, l.target, l.thread)) || [];
          const dim = focus && l.thread !== focus;
          const name = (id) => state.agents[id]?.name || id;
          return html`<g class=${`badge${dim ? " dim" : ""}`} transform=${`translate(${g.mid.x},${g.mid.y})`}>
            <rect x="-15" y="-10" width="30" height="20" rx="10" />
            <text y="4">×${l.count}</text>
            <title>${list.slice(-3).map((m) => `${name(m.from)} → ${name(m.to)} (${m.intent}): ${m.body.slice(0, 80)}`).join("\n")}</title>
          </g>`;
        })}
        ${agents.map((a) => {
          const n = layout.nodes[a.id];
          if (!n) return null;
          const r = nodeRadius(activity[a.id] || 0);
          const dim = focus && !inFocus.has(a.id);
          return html`<g class=${`node ${a.status}${dim ? " dim" : ""}${state.selection.agent === a.id ? " selected" : ""}${effects.shaking.has(a.id) ? " shake" : ""}`}
            data-id=${a.id} transform=${`translate(${n.x},${n.y})`}
            onClick=${() => store.select({ agent: a.id, tab: "overview" })}>
            <circle class="node-fill" r=${r} fill=${companyColor(a.domain)} />
            <circle class="node-ring" r=${r + 3} style=${`--ring:var(${TRUST_TOKENS[a.status] || "--pending"})`} />
            <text class="node-badge" y="4">${a.model === "sonnet" ? "S" : "H"}</text>
            <text class="node-label" x=${r + 10} y="4">${a.name}</text>
          </g>`;
        })}
        ${effects.svgLayer}
      </g>
    </svg>
    <div class="popup-layer">${effects.overlay}</div>
  </div>`;
}
