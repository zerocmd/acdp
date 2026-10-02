// Sequence view: one lane per agent, real time flowing down. Arrow width shows
// message size; lane bands show thinking time; dots show each decision's outcome.
import { html, useEffect, useRef, useState } from "../preact.js";
import { agentsByCompany } from "../store.js";
import { companyColor, threadColor } from "../palette.js";
import { arrowWidth, layoutRows, visibleLanes, yAtTime } from "../lib/sequence.js";
import { PopupCard } from "../components/popup.js";

const LANE_W = 150;
const TOP = 16;
const LEFT = 76;

const outcomeColor = (o = "") => (o === "sent" ? "var(--accent)" : o === "wait" ? "var(--muted)"
  : o.startsWith("rejected") ? "var(--pending)" : "var(--bad)");
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });

export function SequenceView({ store, state }) {
  const box = useRef(null);
  const mountSeq = useRef(state.lastSeq);
  const [follow, setFollow] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const [hover, setHover] = useState(null);
  const { focus, range } = state.selection;
  const messages = state.messages.filter((m) => m.kind === "message"
    && (!focus || m.threadId === focus) && (!range || (m.ts >= range[0] && m.ts <= range[1])));
  const allIds = agentsByCompany(state).flatMap((g) => g.agents.map((a) => a.id));
  const ids = visibleLanes(allIds, messages, { focus, range, showAll });
  const laneX = new Map(ids.map((id, i) => [id, LEFT + i * LANE_W + LANE_W / 2]));
  const first = messages[0]?.ts ?? 0;
  const last = messages[messages.length - 1]?.ts ?? 0;
  const markers = state.timeline.filter((t) => (t.lane === "discover" || t.lane === "verify")
    && laneX.has(t.agent) && t.ts >= first && t.ts <= last);
  const { rows, spacers, height } = layoutRows([
    ...messages.map((m) => ({ ...m, row: "message" })),
    ...markers.map((t) => ({ ...t, row: "marker" })),
  ]);
  const yAt = (ts) => TOP + yAtTime(rows, ts);
  const width = LEFT + ids.length * LANE_W + 20;
  const svgH = TOP + height + 40;
  const rowById = new Map(rows.filter((r) => r.row === "message").map((r) => [r.id, r]));

  useEffect(() => { if (follow && box.current) box.current.scrollTop = box.current.scrollHeight; });
  const onScroll = () => {
    const el = box.current;
    setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };
  return html`<div class="seq-wrap">
    <div class="seq-tools">
      ${focus ? html`<button class="pill" style="--tone:var(--accent)" onClick=${() => store.select({ focus: null })}>Focus: ${focus} ×</button>` : null}
      <label><input type="checkbox" checked=${showAll} onChange=${(e) => setShowAll(e.target.checked)} /> Show all lanes</label>
      <span class="muted">${ids.length} of ${allIds.length} lanes</span>
    </div>
    <div class="seq-scroll" ref=${box} onScroll=${onScroll}>
      <div class="seq-head" style=${`width:${width}px`}>
        ${ids.map((id) => {
          const a = state.agents[id];
          return html`<button class=${`seq-lane-name ${a.status}${state.selection.agent === id ? " selected" : ""}`}
            style=${`left:${laneX.get(id) - LANE_W / 2}px;width:${LANE_W}px;--tone:${companyColor(a.domain)}`}
            onClick=${() => store.select({ agent: id, tab: "overview" })}>
            <strong>${a.name}</strong><span>${a.organization}</span></button>`;
        })}
      </div>
      <svg class="sequence" width=${width} height=${svgH}>
        <defs>${["normal", "bad", "verdict"].map((k) => html`<marker id=${`sq-${k}`} viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class=${`arrowhead ${k}`} /></marker>`)}</defs>
        ${state.selection.agent && laneX.has(state.selection.agent) ? html`<rect class="lane-sel"
          x=${laneX.get(state.selection.agent) - LANE_W / 2} y="0" width=${LANE_W} height=${svgH} />` : null}
        ${ids.map((id) => html`<line class="lane-axis" x1=${laneX.get(id)} x2=${laneX.get(id)} y1="0" y2=${svgH} />`)}
        ${spacers.map((s) => html`<g><line class="spacer" x1="0" x2=${width} y1=${TOP + s.y} y2=${TOP + s.y} />
          <text class="spacer-label" x="6" y=${TOP + s.y - 4}>⋯ ${s.seconds} s</text></g>`)}
        ${rows.filter((r) => r.row === "message").map((r) => html`<text class="clock" x="6" y=${TOP + r.y + 4}>${clock(r.ts)}</text>`)}
        ${ids.flatMap((id) => {
          const a = state.agents[id];
          const x = laneX.get(id);
          const bands = a.intervals.filter((iv) => iv.end >= first && iv.start <= last).map((iv) => html`<rect class="think"
            x=${x - 16} y=${yAt(iv.start)} width="6" height=${Math.max(3, yAt(iv.end) - yAt(iv.start))}><title>thinking ${Math.round(iv.end - iv.start)} s → ${iv.outcome}</title></rect>`);
          const open = a.thinking ? [html`<rect class="think live" x=${x - 16} y=${yAt(a.thinking.start)} width="6" height="14" />`] : [];
          const dots = a.decisions.filter((d) => d.ts >= first && d.ts <= last).map((d) => html`<circle class="decision-dot"
            cx=${x + 14} cy=${yAt(d.ts)} r="4" style=${`fill:${outcomeColor(d.outcome)}`}><title>${d.outcome}</title></circle>`);
          return [...bands, ...open, ...dots];
        })}
        ${Object.values(state.tasks).map((task) => {
          const start = rowById.get(task.messageId);
          if (!start || !laneX.has(task.requester)) return null;
          const end = task.replyId ? rowById.get(task.replyId) : rows[rows.length - 1];
          if (!end) return null;
          const x = laneX.get(task.requester) - 26;
          return html`<path class=${`bracket ${task.state}`} d=${`M${x + 8},${TOP + start.y} H${x} V${TOP + end.y} H${x + 8}`}><title>task ${task.id}: ${task.state}${task.reason ? ` (${task.reason})` : ""}</title></path>`;
        })}
        ${rows.map((r) => {
          const yy = TOP + r.y;
          if (r.row === "marker") {
            const x = laneX.get(r.agent);
            return html`<rect class=${`seq-marker ${r.lane}${r.failed ? " failed" : ""}`} x=${x - 5} y=${yy - 5} width="10" height="10"
              transform=${`rotate(45 ${x} ${yy})`}><title>${r.label}</title></rect>`;
          }
          const x1 = laneX.get(r.from);
          const x2 = laneX.get(r.to);
          if (x1 == null || x2 == null) return null;
          const failed = r.trust && r.trust.status !== "verified";
          const kind = r.intent === "verdict" ? "verdict" : (failed || r.intent === "decline" || r.intent === "challenge") ? "bad" : "normal";
          const fresh = r.seq > mountSeq.current;
          return html`<g class="seq-msg" key=${r.id}
            onMouseEnter=${(e) => setHover({ m: r, x: e.offsetX, y: e.offsetY })} onMouseLeave=${() => setHover(null)}
            onClick=${() => store.select({ focus: r.threadId, thread: r.threadId, allThreads: false })}>
            <line class="hit" x1=${x1} x2=${x2} y1=${yy} y2=${yy} />
            <line class=${`seq-line ${kind}${failed ? " dashed" : ""}${fresh && !failed ? " draw" : ""}`} pathLength=${fresh && !failed ? 1 : null}
              x1=${x1} x2=${x2 + (x2 > x1 ? -7 : 7)} y1=${yy} y2=${yy}
              stroke-width=${kind === "verdict" ? 5 : arrowWidth(r.body)}
              style=${kind === "normal" ? `stroke:${threadColor(r.color)}` : ""} marker-end=${`url(#sq-${kind})`} />
            <text class="seq-label" x=${(x1 + x2) / 2} y=${yy - 6}>${r.intent}</text>
          </g>`;
        })}
        ${state.mode === "live" ? html`<line class="now" x1=${LEFT} x2=${width} y1=${svgH - 24} y2=${svgH - 24} />` : null}
      </svg>
      ${hover ? html`<div class="seq-popup" style=${`left:${hover.x + 12}px;top:${hover.y + 12}px`}>
        <${PopupCard} m=${hover.m} state=${state} /></div>` : null}
    </div>
  </div>`;
}
