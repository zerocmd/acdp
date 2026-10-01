import { test } from "node:test";
import assert from "node:assert/strict";
import { diffKeys } from "../lib/diff.js";

test("diffKeys lists differing and missing top-level keys", () => {
  assert.deepEqual(diffKeys({ a: 1, b: { c: 2 }, d: 3 }, { a: 1, b: { c: 9 }, e: 4 }), ["b", "d", "e"]);
  assert.deepEqual(diffKeys({ a: [1] }, { a: [1] }), []);
  assert.deepEqual(diffKeys(null, { a: 1 }), ["a"]);
});
