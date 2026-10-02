// Comms Map animations: pulses along ribbons, popups, discovery rings, verdict
// bursts, decline shakes, registration rings, and A2A task badges. Only events
// newer than the view's mount animate, so a reconnect or a new replay draws the
// final state without replaying history.
import { html, useEffect, useMemo, useRef, useState } from "../preact.js";
import { threadColor } from "../palette.js";
import { capQueue, freshEvents, placePopup, pointOnCubic, ribbonGeometry } from "../lib/commsmap.js";
import { linkKey } from "./commsmap.js";
import { PopupCard } from "../components/popup.js";

const PULSE_MS = 1200;
const POPUP_MS = 4000;
const SEARCH_MS = 2000;
const BURST_MS = 800;
const SHAKE_MS = 300;
const POP = { w: 240, h: 70 };

function reducedMotion() {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
}

function Pulses({ pulses, setPulses }) {
  const [, setFrame] = useState(0);
  useEffect(() => {
    if (!pulses.length) return undefined;
    let id = 0;
    const loop = () => {
      const now = performance.now();
      if (pulses.some((p) => now - p.start >= PULSE_MS)) {
        setPulses((ps) => ps.filter((p) => performance.now() - p.start < PULSE_MS));
      }
      setFrame((f) => f + 1);
      id = requestAnimationFrame(loop);
    };
    id = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(id);
  }, [pulses]);
  const now = performance.now();
  return pulses.map((p) => {
    const t = Math.min(1, (now - p.start) / PULSE_MS);
    const g = p.geom;
    const head = pointOnCubic(g.p, g.c1, g.c2, g.q, t);
    const tail = pointOnCubic(g.p, g.c1, g.c2, g.q, Math.max(0, t - 0.1));
    return html`<g class="pulse" key=${p.id}>
      <line x1=${tail.x} y1=${tail.y} x2=${head.x} y2=${head.y} style=${`stroke:${p.color}`} />
      <circle cx=${head.x} cy=${head.y} r="6" style=${`fill:${p.color}`} />
    </g>`;
  });
}

function taskSymbol(state) {
  return state === "working" ? "…" : state === "completed" ? "✓" : "✕";
}

export function useMapEffects(state, scene) {
  const { layout, links, view } = scene;
  const since = useRef(state.lastSeq);
  const reduced = useMemo(reducedMotion, []);
  const [pulses, setPulses] = useState([]);
  const [popups, setPopups] = useState([]);
  const [fx, setFx] = useState([]);

  useEffect(() => {
    const from = since.current;
    if (state.lastSeq <= from) return;
    since.current = state.lastSeq;
    const now = performance.now();
    let nextPulses = pulses;
    let nextPopups = popups.filter((p) => p.until > now);
    let nextFx = fx.filter((f) => f.until > now);
    const linkFor = new Map(links.map((l) => [linkKey(l.source, l.target, l.thread), l]));
    for (const m of freshEvents(state.messages.filter((x) => x.kind === "message"), from)) {
      const link = linkFor.get(linkKey(m.from, m.to, m.threadId));
      if (!link) continue;
      const g = ribbonGeometry(link, layout.nodes);
      const geom = link.source === m.from ? g : { p: g.q, c1: g.c2, c2: g.c1, q: g.p };
      const critical = m.intent === "decline" || m.intent === "challenge";
      if (!reduced) {
        nextPulses = capQueue(nextPulses, { id: m.id, key: linkKey(m.from, m.to, m.threadId), geom,
          color: critical ? "var(--bad)" : threadColor(m.color), start: now }, 20);
        if (critical) nextFx = capQueue(nextFx, { id: `shake-${m.id}`, kind: "shake", target: m.to, until: now + SHAKE_MS }, 60);
        if (m.intent === "verdict") nextFx = capQueue(nextFx, { id: `burst-${m.id}`, kind: "burst", target: m.to, until: now + BURST_MS }, 60);
      }
      const spot = placePopup(nextPopups.map((p) => ({ x: p.x, y: p.y, ...POP })), g.mid, POP,
        { w: layout.width, h: layout.height });
      nextPopups = capQueue(nextPopups, { id: m.id, ...spot, m, until: now + POPUP_MS }, 3);
    }
    const query = state.selection.allQueries ? state.lastQuery : state.highlight;
    if (query && query.seq > from) {
      nextFx = capQueue(nextFx, { id: `search-${query.seq}`, kind: "search", target: query.agent,
        results: query.results, capability: query.capability, until: now + SEARCH_MS }, 60);
    }
    for (const t of freshEvents(state.timeline, from)) {
      if (t.type !== "registration.step" || !t.label.includes(": result ")) continue;
      const kind = t.failed ? "shake" : "joined";
      if (!reduced || kind === "joined") {
        nextFx = capQueue(nextFx, { id: `reg-${t.seq}`, kind, target: t.agent, until: now + BURST_MS }, 60);
      }
    }
    setPulses(nextPulses);
    setPopups(nextPopups);
    setFx(nextFx);
  });

  useEffect(() => {
    if (!popups.length && !fx.length) return undefined;
    const timer = setInterval(() => {
      const now = performance.now();
      setPopups((ps) => ps.filter((p) => p.until > now));
      setFx((xs) => xs.filter((f) => f.until > now));
    }, 250);
    return () => clearInterval(timer);
  }, [popups.length > 0 || fx.length > 0]);

  const node = (id) => layout.nodes[id];
  const shaking = new Set(fx.filter((f) => f.kind === "shake").map((f) => f.target));

  const svgLayer = html`<g class="fx">
    ${fx.filter((f) => f.kind === "search" && node(f.target)).map((f) => html`<g key=${f.id}>
      <circle class="search-ring" cx=${node(f.target).x} cy=${node(f.target).y} r="30" />
      ${f.results.filter((r) => node(r.id)).map((r) => html`<g>
        <line class="search-line" x1=${node(f.target).x} y1=${node(f.target).y} x2=${node(r.id).x} y2=${node(r.id).y} />
        ${r.new ? html`<text class="search-new" x=${node(r.id).x} y=${node(r.id).y - 26}>new</text>` : null}
      </g>`)}
      <text class="search-label" x=${node(f.target).x} y=${node(f.target).y + 46}>searching ${f.capability}</text>
    </g>`)}
    ${fx.filter((f) => (f.kind === "burst" || f.kind === "joined") && node(f.target)).map((f) => html`<circle key=${f.id}
      class=${f.kind === "burst" ? "burst" : "joined"} cx=${node(f.target).x} cy=${node(f.target).y} r="22" />`)}
    ${Object.values(state.tasks).map((task) => {
      const link = links.find((l) => linkKey(l.source, l.target, l.thread) === linkKey(task.requester, task.recipient, task.threadId));
      if (!link) return null;
      const g = ribbonGeometry(link, layout.nodes);
      const geom = link.source === task.requester ? g : { p: g.q, c1: g.c2, c2: g.c1, q: g.p };
      const at = pointOnCubic(geom.p, geom.c1, geom.c2, geom.q, 0.14);
      return html`<g key=${task.id} class=${`task-badge ${task.state}`} transform=${`translate(${at.x},${at.y})`}>
        <circle r="9" /><text y="4">${taskSymbol(task.state)}</text><title>task ${task.state}</title></g>`;
    })}
    <${Pulses} pulses=${pulses} setPulses=${setPulses} />
  </g>`;

  const overlay = html`<div class="popups">
    ${popups.map((p) => html`<div key=${p.id} class="popup-wrap"
      style=${`transform: translate(${p.x * view.k + view.x}px, ${p.y * view.k + view.y}px)`}>
      <${PopupCard} m=${p.m} state=${state} /></div>`)}
  </div>`;
  return { svgLayer, overlay, shaking };
}
