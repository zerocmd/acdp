import { test } from "node:test";
import assert from "node:assert/strict";
import { scaleTime } from "../lib/layout.js";

test("scaleTime maps and inverts", () => {
  const s = scaleTime(100, 200, 1000);
  assert.equal(s.x(150), 500);
  assert.equal(s.t(250), 125);
});

test("scaleTime handles a single instant", () => {
  assert.equal(scaleTime(5, 5, 800).x(5), 400);
});
