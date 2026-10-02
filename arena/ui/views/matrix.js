// Matrix view: senders by recipients. Shade = count, border = trust result.
import { html, useRef } from "../preact.js";
import { agentsByCompany, chatItems } from "../store.js";
import { matrixCells } from "../lib/layout.js";
import { inScope, normScope, pairScope } from "../lib/inspect.js";

const CELL = 40;
const HEAD = 200;

export function MatrixView({ store, state }) {
  const ids = agentsByCompany(state).flatMap((g) => g.agents.map((a) => a.id));
  const mountSeq = useRef(state.lastSeq);
  const focus = normScope(state.selection.focus);
  const sel = state.selection.agent;
  const messages = chatItems({ ...state, selection: { ...state.selection, allThreads: true, agent: null, pair: null } })
    .filter((m) => !focus || inScope(focus, m, state.agents));
  const freshPairs = new Set(messages.filter((m) => m.kind === "message" && m.seq > Math.max(mountSeq.current, state.animateAfter))
    .map((m) => `${m.from}>${m.to}`));
  const m = matrixCells(messages, ids);
  const name = (id) => state.agents[id]?.name || id;
  const size = HEAD + ids.length * CELL + 10;
  return html`<div class="view scroll">
    <svg class="matrix" width=${size} height=${size}>
      ${ids.map((id, i) => html`<g>
        <text x=${HEAD - 6} y=${HEAD + i * CELL + CELL / 2 + 4} class=${`m-row ${state.agents[id].status}${id === sel ? " sel" : ""}`}
          onClick=${() => store.select({ agent: id, tab: "overview" })}>${name(id)}</text>
        <text transform=${`translate(${HEAD + i * CELL + CELL / 2 + 4}, ${HEAD - 6}) rotate(-60)`}
          class=${`m-col ${state.agents[id].status}${id === sel ? " sel" : ""}`}>${name(id)}</text>
      </g>`)}
      ${ids.flatMap((from, r) => ids.map((to, c) => {
        const cell = m.cells[`${from}>${to}`];
        const alpha = cell ? 0.15 + 0.85 * (cell.count / m.max) : 0;
        const cls = cell ? (cell.failed ? "failed" : cell.verified ? "verified" : "") : "";
        return html`<rect x=${HEAD + c * CELL} y=${HEAD + r * CELL} width=${CELL - 2} height=${CELL - 2}
          class=${`m-cell ${cls}${from === to ? " self" : ""}${freshPairs.has(`${from}>${to}`) ? " flash" : ""}${sel && (from === sel || to === sel) ? " selrow" : ""}`} fill-opacity=${alpha}
          onClick=${() => cell && store.select({ inspect: pairScope(from, to, "agent") })}>
          <title>${cell ? `${name(from)} → ${name(to)}: ${cell.count}\n${cell.bodies.join("\n")}` : `${name(from)} → ${name(to)}: none`}</title>
        </rect>`;
      }))}
    </svg>
  </div>`;
}
