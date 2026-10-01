// Workbench layout and the event stream.
import { html, render, useEffect, useState } from "./preact.js";
import { createStore } from "./store.js";
import { Topbar } from "./components/topbar.js";
import { Sidebar } from "./components/sidebar.js";
import { ViewSwitch } from "./components/viewswitch.js";
import { Legend } from "./components/legend.js";
import { AddAgent } from "./components/addagent.js";
import { Chat } from "./components/chat.js";
import { NetworkView } from "./views/network.js";
import { Timeline } from "./components/timeline.js";
import { Drawer } from "./components/drawer.js";
import { RegistryView } from "./components/registry.js";

const store = createStore();

// Tasks 10, 13, 14, and 15 add entries.
export const VIEWS = {
  network: ["Network", NetworkView],
  registry: ["Registry", RegistryView],
};

export function RIGHT(state) {
  return state.selection.agent && state.agents[state.selection.agent] ? Drawer : Chat;
}

export function TIMELINE() {
  return Timeline;
}

function useStoreState() {
  const [, setTick] = useState(0);
  useEffect(() => {
    let frame = 0;
    // Batch renders. setTimeout, not requestAnimationFrame: rAF never fires in a
    // hidden tab, so a backgrounded Workbench would stop updating.
    const unsubscribe = store.subscribe(() => {
      if (frame) return;
      frame = setTimeout(() => { frame = 0; setTick((n) => n + 1); }, 16);
    });
    // Events can arrive before this effect runs (it runs after paint), so
    // render once now to catch up with them.
    setTick((n) => n + 1);
    return unsubscribe;
  }, []);
  return store.get();
}

function Splitter() {
  const start = (event) => {
    const body = event.currentTarget.parentElement;
    const move = (e) => {
      const width = Math.min(800, Math.max(300, body.getBoundingClientRect().right - e.clientX));
      body.style.setProperty("--right-w", `${width}px`);
    };
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };
  return html`<div class="splitter" onMouseDown=${start}></div>`;
}

function App() {
  const state = useStoreState();
  const view = VIEWS[state.selection.view] || VIEWS.network;
  const View = view[1];
  const Right = RIGHT(state);
  const Timeline = TIMELINE();
  return html`<div class="wb">
    <${Topbar} store=${store} state=${state} />
    <div class="wb-body">
      <${Sidebar} store=${store} state=${state} />
      <main class="wb-center">
        <${ViewSwitch} store=${store} state=${state} views=${VIEWS} />
        <div class="view"><${View} store=${store} state=${state} /></div>
        <div class="timeline-slot">${Timeline ? html`<${Timeline} store=${store} state=${state} />` : null}</div>
        <${Legend} />
      </main>
      <${Splitter} />
      <aside class="right"><${Right} store=${store} state=${state} /></aside>
    </div>
    <div class="debug">${state.unknown ? `${state.unknown} unknown events ignored` : ""}</div>
    <${AddAgent} store=${store} state=${state} />
  </div>`;
}

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws`);
  socket.onopen = () => store.reset();
  socket.onmessage = (message) => store.dispatch(JSON.parse(message.data));
  socket.onclose = () => { store.setMode("reconnecting"); setTimeout(connect, 2000); };
}

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") store.select({ agent: null, range: null, adding: false });
});

render(html`<${App} />`, document.getElementById("root"));
connect();
