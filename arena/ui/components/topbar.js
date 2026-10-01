import { html, useEffect, useState } from "../preact.js";
import { getJson, postJson } from "../api.js";

function modeLabel(state) {
  if (state.mode === "replay") return `replay ${state.log}`;
  if (state.mode === "live") return state.paused ? "live · paused" : "live";
  if (state.mode === "stopped") return `stopped: ${state.stopReason}`;
  return state.mode;
}

export function Topbar({ store, state }) {
  const [logs, setLogs] = useState([]);
  const [log, setLog] = useState("");
  const [speed, setSpeed] = useState(2);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    getJson("/arena/logs").then((d) => { setLogs(d.logs); setLog((cur) => cur || d.logs[0] || ""); })
      .catch(() => setLogs([]));
  }, [state.mode]);
  const messages = state.messages.filter((m) => m.kind === "message").length;
  const open = Object.values(state.threads).filter((t) => !t.closed).length;
  const pause = () => postJson(state.paused ? "/arena/resume" : "/arena/pause").catch((e) => setError(e.message));
  const replay = async () => {
    setBusy(true);
    setError("");
    try { await postJson("/arena/replay", { log, speed }); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  return html`<header class="topbar">
    <strong>ACDP Arena Workbench</strong>
    <span class="chip">${modeLabel(state)}</span>
    <span class="muted">${state.order.length} agents · ${messages} messages · ${open} open threads</span>
    ${error ? html`<span class="error">${error}</span>` : null}
    <span class="spacer"></span>
    <button onClick=${pause} disabled=${state.mode !== "live"}>${state.paused ? "Resume" : "Pause"}</button>
    <select value=${log} onChange=${(e) => setLog(e.target.value)} aria-label="Saved run">
      ${logs.map((name) => html`<option value=${name}>${name}</option>`)}
    </select>
    <label class="muted">Speed <input type="range" min="1" max="10" value=${speed}
      onInput=${(e) => setSpeed(Number(e.target.value))} /></label>
    <button onClick=${replay} disabled=${!log || busy}>Replay</button>
    <button class="primary" onClick=${() => store.select({ adding: true })}>+ Agent</button>
  </header>`;
}
