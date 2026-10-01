import { html, useRef, useState } from "../preact.js";
import { scaleTime } from "../lib/layout.js";

const LANES = [["register", "Register"], ["discover", "Discover"], ["verify", "Verify"], ["message", "Message"]];
const TAB_FOR_LANE = { register: "overview", discover: "discovery", verify: "discovery", message: "activity" };
const LEFT = 70;
const LANE_H = 26;

export function Timeline({ store, state }) {
  const svg = useRef(null);
  const [drag, setDrag] = useState(null);
  const items = state.timeline;
  const width = Math.max(200, (svg.current?.clientWidth || 800) - LEFT - 10);
  const t0 = items.length ? items[0].ts : 0;
  const t1 = items.length ? items[items.length - 1].ts : 1;
  const scale = scaleTime(t0, t1, width);
  const range = state.selection.range;
  const localX = (e) => e.clientX - svg.current.getBoundingClientRect().left - LEFT;
  const down = (e) => setDrag({ from: localX(e), to: localX(e) });
  const move = (e) => drag && setDrag({ ...drag, to: localX(e) });
  const up = () => {
    if (drag && Math.abs(drag.to - drag.from) > 4) {
      const a = scale.t(Math.min(drag.from, drag.to));
      const b = scale.t(Math.max(drag.from, drag.to));
      store.select({ range: [a, b] });
    }
    setDrag(null);
  };
  return html`<svg class="timeline" ref=${svg} onMouseDown=${down} onMouseMove=${move} onMouseUp=${up}>
    ${LANES.map(([lane, label], i) => html`<g>
      <text x="6" y=${i * LANE_H + 18} class="lane-label">${label}</text>
      <line x1=${LEFT} x2=${LEFT + width} y1=${i * LANE_H + 14} y2=${i * LANE_H + 14} class="lane-line" />
    </g>`)}
    ${range ? html`<rect class="range" x=${LEFT + scale.x(range[0])} y="0"
      width=${Math.max(2, scale.x(range[1]) - scale.x(range[0]))} height=${LANES.length * LANE_H} />` : null}
    ${drag ? html`<rect class="range" x=${LEFT + Math.min(drag.from, drag.to)} y="0"
      width=${Math.abs(drag.to - drag.from)} height=${LANES.length * LANE_H} />` : null}
    ${items.map((it) => {
      const lane = LANES.findIndex(([key]) => key === it.lane);
      const selected = it.agent && it.agent === state.selection.agent;
      return html`<circle cx=${LEFT + scale.x(it.ts)} cy=${lane * LANE_H + 14} r=${selected ? 5 : 3.5}
        class=${`tl-dot ${it.lane}${it.failed ? " failed" : ""}${selected ? " selected" : ""}`}
        onMouseDown=${(e) => e.stopPropagation()}
        onClick=${() => it.agent && store.select({ agent: it.agent, tab: TAB_FOR_LANE[it.lane] })}>
        <title>${it.label}</title></circle>`;
    })}
  </svg>`;
}
