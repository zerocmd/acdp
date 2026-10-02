import { html, useEffect, useRef, useState } from "../preact.js";
import { chatItems } from "../store.js";
import { companyColor, threadColor } from "../palette.js";

function Chips({ store, state }) {
  const { thread, allThreads } = state.selection;
  return html`<div class="chips">
    ${state.threadOrder.map((id) => {
      const t = state.threads[id];
      const on = !allThreads && thread === id;
      return html`<button class=${`chip-btn${on ? " on" : ""}`} style=${`--tc:${threadColor(t.color)}`}
        onClick=${() => store.select({ thread: id, allThreads: false, agent: null })}>
        ${id} ${t.title.slice(0, 24)} · ${t.count}${t.closed ? " ✓" : ""}${t.unread ? html` <span class="unread"></span>` : null}
      </button>`;
    })}
    <button class=${`chip-btn${allThreads ? " on" : ""}`} onClick=${() => store.select({ allThreads: true, agent: null })}>All threads</button>
  </div>`;
}

function Bubble({ m, state, all }) {
  const from = state.agents[m.from] || { name: m.from, organization: "", domain: "", model: "" };
  const to = state.agents[m.to] || { name: m.to };
  const failed = m.trust && m.trust.status !== "verified";
  const taskId = state.taskByMessage[m.id];
  const task = taskId ? state.tasks[taskId] : null;
  return html`<div class=${`msg${m.replyTo ? " reply" : ""}${all ? " rail" : ""}`} style=${`--tc:${threadColor(m.color)}`}>
    <span class="avatar" style=${`background:${companyColor(from.domain)}`}>${from.model === "sonnet" ? "S" : "H"}</span>
    <div class="msg-main">
      <div class="msg-head"><strong>${from.name}</strong>
        <span class="muted">${from.organization} (${from.domain}) → ${to.name} · ${m.intent} · ${new Date(m.ts * 1000).toLocaleTimeString()}${all ? ` · ${m.threadId}` : ""}</span>
        ${m.trust ? html`<span class=${`trust ${failed ? "bad" : "ok"}`}>${failed ? `✕ ${m.trust.reason}` : "✓ verified"}</span>` : null}
        ${task ? html`<span class=${`chip task ${task.state}`}>${task.state}</span>` : null}
      </div>
      <div class=${`bubble${failed ? " failed" : ""}`}>${m.body}</div>
      ${m.lookingFor || m.whyThisPeer ? html`<div class="intent-line">looking for: ${m.lookingFor || "—"} · why: ${m.whyThisPeer || "—"}</div>` : null}
    </div>
  </div>`;
}

export function Chat({ store, state }) {
  const box = useRef(null);
  const [follow, setFollow] = useState(true);
  const items = chatItems(state);
  const all = state.selection.allThreads;
  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  });
  const onScroll = () => {
    const el = box.current;
    setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };
  return html`<div class="chat">
    <${Chips} store=${store} state=${state} />
    <div class="feed" ref=${box} onScroll=${onScroll}>
      ${items.map((m) => m.kind === "system"
        ? html`<div class="divider"><span>${m.text}</span></div>`
        : html`<${Bubble} m=${m} state=${state} all=${all} />`)}
      ${items.length ? null : html`<p class="muted">No messages in this view yet.</p>`}
    </div>
    ${follow ? null : html`<button class="pill-btn" onClick=${() => setFollow(true)}>New messages ↓</button>`}
  </div>`;
}
