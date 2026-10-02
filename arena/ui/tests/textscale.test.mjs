import { test } from "node:test";
import assert from "node:assert/strict";
import { clampScale, MAX, MIN, stepScale } from "../lib/textscale.js";

test("clampScale bounds and rounds", () => {
  assert.equal(clampScale(2), MAX);
  assert.equal(clampScale(0.1), MIN);
  assert.equal(clampScale("x"), 1);
  assert.equal(clampScale(1.04999), 1.05);
});

test("stepScale moves by one step inside the bounds", () => {
  assert.equal(stepScale(1, 1), 1.05);
  assert.equal(stepScale(1, -1), 0.95);
  assert.equal(stepScale(MAX, 1), MAX);
});
