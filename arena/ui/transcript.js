// Transcript feed with combined filters.
const MAX_ITEMS = 2000;

export function createTranscript(feed, selects, { threadColor, companyOf }) {
  const filters = { thread: "", agent: "", company: "", intent: "" };
  let items = [];

  function matches(item) {
    if (filters.thread && item.thread !== filters.thread) return false;
    if (filters.agent && item.from !== filters.agent && item.to !== filters.agent) return false;
    if (filters.company && companyOf(item.from) !== filters.company
        && companyOf(item.to) !== filters.company) return false;
    if (filters.intent && item.intent !== filters.intent) return false;
    return true;
  }

  function render(item) {
    const li = document.createElement("li");
    if (item.intent === "system") {
      li.className = "system";
      li.textContent = item.text;
      return li;
    }
    const head = document.createElement("div");
    head.className = "head";
    const chip = document.createElement("span");
    chip.className = "thread";
    chip.style.background = threadColor(item.color);
    chip.title = item.thread;
    const who = document.createElement("span");
    who.textContent = `${item.from} → ${item.to}`;
    const intent = document.createElement("span");
    intent.className = `intent ${item.intent}`;
    intent.textContent = item.intent;
    head.append(chip, who, intent);
    const body = document.createElement("div");
    body.className = "body";
    body.textContent = item.text;
    li.append(head, body);
    return li;
  }

  function rerender() {
    feed.replaceChildren(...items.filter(matches).map(render));
    feed.scrollTop = feed.scrollHeight;
  }

  for (const [key, select] of Object.entries(selects)) {
    select.addEventListener("change", () => { filters[key] = select.value; rerender(); });
  }

  return {
    add(item) {
      items.push(item);
      if (items.length > MAX_ITEMS) items = items.slice(-MAX_ITEMS);
      if (!matches(item)) return;
      const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
      feed.append(render(item));
      if (nearBottom) feed.scrollTop = feed.scrollHeight;
    },
    system(text) { this.add({ intent: "system", text, thread: "", from: "", to: "" }); },
    addOption(kind, value, label) {
      const select = selects[kind];
      if ([...select.options].some((o) => o.value === value)) return;
      select.append(new Option(label, value));
    },
    setFilter(kind, value) { filters[kind] = value; selects[kind].value = value; rerender(); },
    clearFilters() { for (const k of Object.keys(filters)) this.setFilter(k, ""); },
    reset() {
      items = [];
      feed.replaceChildren();
      for (const [kind, select] of Object.entries(selects)) {
        if (kind !== "intent") select.replaceChildren(select.options[0]);
        filters[kind] = "";
        select.value = "";
      }
    },
  };
}
