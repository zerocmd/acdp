import { test } from "node:test";
import assert from "node:assert/strict";
import { arrowWidth, layoutRows, visibleLanes, yAtTime } from "../lib/sequence.js";

test("layoutRows spaces by time and compresses long gaps", () => {
  const { rows, spacers } = layoutRows([{ seq: 1, ts: 0 }, { seq: 2, ts: 10 }, { seq: 3, ts: 11 }, { seq: 4, ts: 100 }]);
  assert.deepEqual(rows.map((r) => r.y), [0, 60, 88, 142]);
  assert.deepEqual(spacers, [{ y: 116, seconds: 89 }]);
});

test("layoutRows orders by ts then seq", () => {
  const { rows } = layoutRows([{ seq: 2, ts: 5 }, { seq: 1, ts: 5 }, { seq: 3, ts: 1 }]);
  assert.deepEqual(rows.map((r) => r.seq), [3, 1, 2]);
});

test("yAtTime interpolates and clamps", () => {
  const rows = [{ ts: 0, y: 0 }, { ts: 10, y: 100 }];
  assert.equal(yAtTime(rows, 5), 50);
  assert.equal(yAtTime(rows, -3), 0);
  assert.equal(yAtTime(rows, 99), 100);
  assert.equal(yAtTime([], 5), 0);
});

test("arrowWidth buckets by body length", () => {
  assert.equal(arrowWidth("x".repeat(50)), 2);
  assert.equal(arrowWidth("x".repeat(200)), 3.5);
  assert.equal(arrowWidth("x".repeat(500)), 5);
  assert.equal(arrowWidth(undefined), 2);
});

test("visibleLanes keeps lanes active in the focus or range", () => {
  const ms = [{ threadId: "t1", from: "a", to: "b", ts: 1 }, { threadId: "t2", from: "c", to: "d", ts: 50 }];
  const ids = ["a", "b", "c", "d", "e"];
  assert.deepEqual(visibleLanes(ids, ms, { focus: "t2" }), ["c", "d"]);
  assert.deepEqual(visibleLanes(ids, ms, { range: [0, 10] }), ["a", "b"]);
  assert.deepEqual(visibleLanes(ids, ms, {}), ["a", "b", "c", "d"]);
  assert.deepEqual(visibleLanes(ids, ms, { showAll: true }), ids);
  assert.deepEqual(visibleLanes(ids, [], { focus: "t9" }), ids);
});
