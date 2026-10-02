// Text-size scale for the whole UI. Pure.
export const MIN = 0.85;
export const MAX = 1.3;
export const STEP = 0.05;

export function clampScale(x) {
  const n = Number(x);
  if (!Number.isFinite(n)) return 1;
  return Math.round(Math.min(MAX, Math.max(MIN, n)) * 100) / 100;
}

export function stepScale(current, direction) {
  return clampScale(clampScale(current) + STEP * Math.sign(direction));
}
