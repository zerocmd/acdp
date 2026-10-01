// Top-level JSON difference between two objects. Pure.

// JSON text with object keys sorted at every level, so key order never
// counts as a difference (the registry and the live card order keys differently).
function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${stable(value[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function diffKeys(a, b) {
  const left = a || {};
  const right = b || {};
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
  return [...keys].filter((k) => stable(left[k]) !== stable(right[k])).sort();
}
