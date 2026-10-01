// Small fetch helpers. Errors carry the server's message.
async function parse(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.error || (body.detail && JSON.stringify(body.detail)) || response.status;
    throw new Error(String(detail));
  }
  return body;
}

export async function getJson(path) {
  return parse(await fetch(path, { cache: "no-store" }));
}

export async function postJson(path, body) {
  return parse(await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  }));
}
