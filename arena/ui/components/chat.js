// Chat: one thread at a time (or all threads), larger type, a Setup card instead
// of join and verify lines, and links to the Comms Map (hover glows the ribbon,
// click focuses the thread).
import { html, useEffect, useRef, useState } from "../preact.js";
import { chatItems } from "../store.js";
import { companyColor, threadColor } from "../palette.js";
import { Chip } from "./cards.js";

function SetupCard({ state }) {
  const [open, setOpen] = useState(false);
  const all = Object.values(state.agents);
  if (!all.length) return null;
  const verified = all.filter((a) => a.status === "verified").length;
  const failed = all.filter((a) => a.status === "failed").length;
  const lines = state.messages.filter((m) => m.kind === "system" && m.sub === "setup");
  return html`<section class="sec setup">
    <div class="sec-title">Setup · ${all.length} agents</div>
    <${Chip} tone="ok">${verified} verified<//>
    ${failed ? html`<${Chip} tone="bad">${failed} failed<//>` : null}
    <button class="link" onClick=${() => setOpen(!open)}>${open ? "hide details ▾" : "show details ▸"}</button>
    ${open ? html`<ul class="setup-lines">${lines.map((l) => html`<li key=${l.id}>${l.text}</li>`)}</ul>` : null}
  </section>`;
}

function Chips({ store, state }) {
  const { thread, allThreads } = state.selection;
  return html`<div class="chips">
    ${state.threadOrder.map((id) => {
      const t = state.threads[id];
      const on = !allThreads && thread === id;
      return html`<button key=${id} class=${`chip-btn${on ? " on" : ""}`} style=${`--tc:${threadColor(t.color)}`}
        onClick=${() => store.select({ thread: id, allThreads: false, agent: null, focus: id })}>
        ${id} ${t.title.slice(0, 26)} · ${t.count}${t.closed ? " ✓" : ""}${t.unread ? html` <span class="unread"></span>` : null}
      </button>`;
    })}
    <button class=${`chip-btn${allThreads ? " on" : ""}`}
      onClick=${() => store.select({ allThreads: true, agent: null, focus: null })}>All threads</button>
  </div>`;
}

function Bubble({ m, state, store, all, fresh }) {
  const from = state.agents[m.from] || { name: m.from, organization: "", domain: "", model: "" };
  const to = state.agents[m.to] || { name: m.to };
  const failed = m.trust && m.trust.status !== "verified";
  const taskId = state.taskByMessage[m.id];
  const task = taskId ? state.tasks[taskId] : null;
  const taskTone = task ? (task.state === "completed" ? "ok" : task.state === "working" ? "pending" : "bad") : null;
  return html`<div class=${`msg${m.replyTo ? " reply" : ""}${fresh ? " fresh" : ""}`}
    onMouseEnter=${() => store.select({ hoverMessage: m.id })} onMouseLeave=${() => store.select({ hoverMessage: null })}
    onClick=${() => store.select({ focus: m.threadId })}>
    <span class=${`avatar${failed ? " failed" : ""}`} style=${`background:${failed ? "var(--panel)" : companyColor(from.domain)}`}>
      ${from.model === "sonnet" ? "S" : "H"}</span>
    <div class="msg-main">
      <div class="msg-head"><strong class=${failed ? "bad" : ""}>${from.name}</strong>
        <span class="muted">${from.organization} (${from.domain}) → ${to.name} · ${new Date(m.ts * 1000).toLocaleTimeString()}</span>
      </div>
      <div class=${`bubble${failed ? " failed" : ""}`}>${m.body}</div>
      <div class="msg-chips">
        <${Chip} tone=${m.intent === "decline" || m.intent === "challenge" ? "bad" : m.intent === "verdict" ? "ok" : "info"}>${m.intent}<//>
        ${all ? html`<${Chip} tone=${threadColor(m.color)}>${m.threadId}<//>` : null}
        ${m.trust ? html`<${Chip} tone=${failed ? "bad" : "ok"}>${failed ? `✕ ${m.trust.reason}` : "✓ verified"}<//>` : null}
        ${task ? html`<${Chip} tone=${taskTone}>task ${task.state}<//>` : null}
      </div>
      ${m.lookingFor || m.whyThisPeer ? html`<div class="intent-line">looking for: ${m.lookingFor || "—"} · why: ${m.whyThisPeer || "—"}</div>` : null}
    </div>
  </div>`;
}

export function Chat({ store, state }) {
  const box = useRef(null);
  const mountSeq = useRef(state.lastSeq);
  const [follow, setFollow] = useState(true);
  const items = chatItems(state);
  const all = state.selection.allThreads;
  useEffect(() => { if (follow && box.current) box.current.scrollTop = box.current.scrollHeight; });
  const onScroll = () => {
    const el = box.current;
    setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };
  return html`<div class="chat">
    <${Chips} store=${store} state=${state} />
    <div class="feed" ref=${box} onScroll=${onScroll}>
      <${SetupCard} state=${state} />
      ${items.map((m) => (m.kind === "system"
        ? html`<div key=${m.id} class="divider"><span>${m.text}</span></div>`
        : html`<${Bubble} key=${m.id} m=${m} state=${state} store=${store} all=${all} fresh=${m.seq > Math.max(mountSeq.current, state.animateAfter)} />`))}
      ${items.length ? null : html`<p class="muted">No messages in this view yet.</p>`}
    </div>
    ${follow ? null : html`<button class="pill-btn" onClick=${() => setFollow(true)}>New messages ↓</button>`}
  </div>`;
}
