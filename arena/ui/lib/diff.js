// Top-level JSON difference between two objects. Pure.
export function diffKeys(a, b) {
  const left = a || {};
  const right = b || {};
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
  return [...keys].filter((k) => JSON.stringify(left[k]) !== JSON.stringify(right[k])).sort();
}
