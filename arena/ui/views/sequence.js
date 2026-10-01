// Sequence view: one lane per agent, time flows down.
import { html, useEffect, useRef, useState } from "../preact.js";
import { agentsByCompany, chatItems } from "../store.js";
import { companyColor, threadColor } from "../palette.js";
import { sequenceRows } from "../lib/layout.js";

const LANE_W = 120;
const ROW_H = 26;
const TOP = 44;
const LEFT = 20;

// Task 18 fills this in.
export function taskBrackets(rows, state) {
  return [];
}

export function SequenceView({ store, state }) {
  const box = useRef(null);
  const [follow, setFollow] = useState(true);
  const lanes = agentsByCompany(state).flatMap((g) => g.agents);
  const laneX = new Map(lanes.map((a, i) => [a.id, LEFT + i * LANE_W + LANE_W / 2]));
  const messages = chatItems(state).filter((m) => m.kind === "message");
  const first = messages[0]?.seq ?? -1;
  const last = messages[messages.length - 1]?.seq ?? -1;
  const markers = state.timeline.filter((t) => (t.lane === "discover" || t.lane === "verify")
    && laneX.has(t.agent) && t.seq >= first && t.seq <= last);
  const rows = sequenceRows(messages, markers);
  const width = LEFT * 2 + lanes.length * LANE_W;
  const height = TOP + rows.length * ROW_H + 20;
  useEffect(() => { if (follow && box.current) box.current.scrollTop = box.current.scrollHeight; });
  const onScroll = () => {
    const el = box.current;
    setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };
  return html`<div class="view scroll" ref=${box} onScroll=${onScroll}>
    <svg class="sequence" width=${width} height=${height}>
      <defs>${["normal", "bad", "verdict"].map((k) => html`<marker id=${`arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5"
        markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class=${`arrowhead ${k}`} /></marker>`)}</defs>
      ${lanes.map((a) => html`<g class="lane" onClick=${() => store.select({ agent: a.id, tab: "overview" })}>
        <text x=${laneX.get(a.id)} y="16" class=${`lane-name ${a.status}`}>${a.name}</text>
        <text x=${laneX.get(a.id)} y="30" class="lane-org" fill=${companyColor(a.domain)}>${a.organization}</text>
        <line x1=${laneX.get(a.id)} x2=${laneX.get(a.id)} y1=${TOP - 6} y2=${height} class="lane-axis" />
      </g>`)}
      ${taskBrackets(rows, state).map((b) => html`<path d=${b.path} class=${`bracket ${b.state}`}><title>${b.label}</title></path>`)}
      ${rows.map((r) => {
        const y = TOP + r.index * ROW_H + 10;
        if (r.kind === "marker") {
          const x = laneX.get(r.agent);
          return html`<g><rect x=${x - 4} y=${y - 4} width="8" height="8" transform=${`rotate(45 ${x} ${y})`}
            class=${`seq-marker ${r.lane}${r.failed ? " failed" : ""}`} /><title>${r.label}</title></g>`;
        }
        const x1 = laneX.get(r.from); const x2 = laneX.get(r.to);
        if (x1 == null || x2 == null) return null;
        const failed = r.trust && r.trust.status !== "verified";
        const kind = r.intent === "verdict" ? "verdict" : failed || r.intent === "decline" || r.intent === "challenge" ? "bad" : "normal";
        return html`<g class="seq-msg" onClick=${() => store.select({ thread: r.threadId, allThreads: false, agent: null })}>
          <line x1=${x1} x2=${x2 + (x2 > x1 ? -6 : 6)} y1=${y} y2=${y} class=${`seq-line ${kind}${failed ? " dashed" : ""}`}
            stroke=${kind === "normal" ? threadColor(r.color) : null} marker-end=${`url(#arrow-${kind})`} />
          <text x=${(x1 + x2) / 2} y=${y - 4} class="seq-label">${r.intent}</text>
          <title>${r.body}</title>
        </g>`;
      })}
    </svg>
  </div>`;
}
