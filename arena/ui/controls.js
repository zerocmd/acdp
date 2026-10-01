// Control bar and add-agent dialog.
async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.error || (data.detail && JSON.stringify(data.detail)) || response.status;
    throw new Error(String(detail));
  }
  return data;
}

export function createControls() {
  const $ = (id) => document.getElementById(id);
  const pause = $("pause");
  const dialog = $("add-dialog");
  const form = $("add-form");
  const error = $("add-error");
  let paused = false;

  pause.addEventListener("click", async () => {
    await post(paused ? "/arena/resume" : "/arena/pause");
  });

  async function loadLogs() {
    const { logs } = await (await fetch("/arena/logs")).json();
    $("logs").replaceChildren(...logs.map((name) => new Option(name, name)));
  }
  $("replay").addEventListener("click", async () => {
    const log = $("logs").value;
    if (log) await post("/arena/replay", { log, speed: Number($("speed").value) });
  });

  $("add").addEventListener("click", () => { error.textContent = ""; dialog.showModal(); });
  $("add-cancel").addEventListener("click", () => dialog.close());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    const body = {
      ...data,
      needs: (data.needs || "").split(",").map((s) => s.trim()).filter(Boolean),
      generate: data.generate === "on",
    };
    try {
      await post("/arena/agents", body);
      form.reset();
      dialog.close();
    } catch (e) {
      error.textContent = e.message;
    }
  });

  loadLogs().catch(() => {});

  return {
    setPaused(value) { paused = value; pause.textContent = value ? "Resume" : "Pause"; },
    setMode(text) { $("mode").textContent = text; },
    setStats({ agents, messages, threads }) {
      $("stats").textContent = `${agents} agents · ${messages} messages · ${threads} open threads`;
    },
    loadLogs,
  };
}
