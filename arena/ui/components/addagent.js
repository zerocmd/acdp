import { html, useEffect, useRef, useState } from "../preact.js";
import { postJson } from "../api.js";

export function AddAgent({ store, state }) {
  const dialog = useRef(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const el = dialog.current;
    if (state.selection.adding && !el.open) { setError(""); el.showModal(); }
    if (!state.selection.adding && el.open) el.close();
  }, [state.selection.adding]);
  const submit = async (event) => {
    event.preventDefault();
    // currentTarget is null after the first await, so keep the form now.
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    const body = { ...data, generate: data.generate === "on",
      needs: (data.needs || "").split(",").map((s) => s.trim()).filter(Boolean) };
    setBusy(true);
    try {
      await postJson("/arena/agents", body);
      form.reset();
      store.select({ adding: false });
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  return html`<dialog ref=${dialog} onClose=${() => store.select({ adding: false })}>
    <form onSubmit=${submit}>
      <h2>Add agent</h2>
      <label>Name <input name="name" required maxlength="60" /></label>
      <label>Organization <input name="organization" required maxlength="80" /></label>
      <label>Domain <input name="domain" required placeholder="coastal-bank.example" /></label>
      <label>Capability <input name="capability" required pattern="[a-z0-9-]{1,40}" /></label>
      <label>Needs (comma-separated) <input name="needs" placeholder="soc-investigation" /></label>
      <label>Model <select name="model"><option value="haiku">Haiku</option><option value="sonnet">Sonnet</option></select></label>
      <label>Agenda <textarea name="agenda" rows="3" maxlength="1000"></textarea></label>
      <label><input type="checkbox" name="generate" /> Generate prompt with Sonnet</label>
      <label>Misconfigure <select name="misconfigure">
        <option value="none">None</option><option value="no_txt">Missing TXT record</option>
        <option value="wrong_key">Wrong key in DNS</option></select></label>
      <p class="error" role="alert">${error}</p>
      <div class="actions">
        <button type="button" onClick=${() => store.select({ adding: false })}>Cancel</button>
        <button type="submit" class="primary" disabled=${busy}>${busy ? "Adding…" : "Add"}</button>
      </div>
    </form>
  </dialog>`;
}
