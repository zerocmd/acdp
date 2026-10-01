import { test } from "node:test";
import assert from "node:assert/strict";
import { scaleTime, convexHull, expandPoints, flowGraph, hullLabelPoint, matrixCells, sequenceRows, threadLinks } from "../lib/layout.js";

test("scaleTime maps and inverts", () => {
  const s = scaleTime(100, 200, 1000);
  assert.equal(s.x(150), 500);
  assert.equal(s.t(250), 125);
});

test("scaleTime handles a single instant", () => {
  assert.equal(scaleTime(5, 5, 800).x(5), 400);
});

const msg = (seq, from, to, threadId = "t1", intent = "share", trust = null) =>
  ({ kind: "message", id: `m${seq}`, seq, threadId, from, to, intent, color: 0, trust, body: `b${seq}` });

test("convexHull drops interior points", () => {
  const hull = convexHull([{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 4 }, { x: 0, y: 4 }, { x: 2, y: 2 }]);
  assert.equal(hull.length, 4);
  assert.ok(!hull.some((p) => p.x === 2 && p.y === 2));
});

test("expandPoints and hullLabelPoint", () => {
  const pts = expandPoints([{ x: 10, y: 10 }], 5);
  assert.equal(pts.length, 4);
  assert.deepEqual(hullLabelPoint(convexHull(pts)), { x: 5, y: 5 });
});

test("threadLinks aggregates per pair and thread with spread curvature", () => {
  const links = threadLinks([msg(1, "a", "b"), msg(2, "b", "a"), msg(3, "a", "b", "t2", "decline")]);
  assert.equal(links.length, 2);
  const t1 = links.find((l) => l.thread === "t1");
  assert.equal(t1.count, 2);
  assert.equal(t1.curvature, 0);
  const t2 = links.find((l) => l.thread === "t2");
  assert.equal(t2.critical, true);
  assert.equal(t2.curvature, 0.25);
});

test("matrixCells counts and flags trust", () => {
  const m = matrixCells([msg(1, "a", "b", "t1", "share", { status: "verified" }),
    msg(2, "c", "b", "t1", "share", { status: "failed", reason: "domain mismatch" }),
    msg(3, "a", "b")], ["a", "b", "c"]);
  assert.equal(m.cells["a>b"].count, 2);
  assert.equal(m.cells["a>b"].verified, true);
  assert.equal(m.cells["c>b"].failed, true);
  assert.equal(m.max, 2);
});

test("flowGraph orders nodes by first appearance and keeps loops", () => {
  const g = flowGraph([msg(1, "soc", "intel"), msg(2, "intel", "soc", "t1", "reply"),
    msg(3, "soc", "isac"), msg(4, "isac", "soc", "t1", "verdict"), msg(5, "x", "y", "t2")], "t1");
  assert.deepEqual(g.nodes, ["soc", "intel", "isac"]);
  assert.equal(g.root, "soc");
  assert.deepEqual(g.edges.find((e) => e.from === "isac").intents, ["verdict"]);
  assert.equal(g.edges.length, 4);
});

test("sequenceRows merges messages and markers by seq", () => {
  const rows = sequenceRows([msg(2, "a", "b"), msg(5, "b", "a")], [{ seq: 3, agent: "a", lane: "discover", label: "q" }]);
  assert.deepEqual(rows.map((r) => [r.index, r.kind, r.seq]), [[0, "message", 2], [1, "marker", 3], [2, "message", 5]]);
});
